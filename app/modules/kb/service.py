"""
知识库管理业务层: 上传、文档、任务、分块维护。
"""
import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import APP_ROOT, settings
from app.core.logging import get_logger
from app.modules.admin.exceptions import (
    ProductHasActiveJobError,
    ProductNotFoundError,
)
from app.modules.product.models import Product
from app.rag.maintenance import purge_product_knowledge
from app.rag.storage import (
    StorageError,
    atomic_write_bytes,
    build_storage_stem,
    validate_markdown,
    validate_pdf,
)

from .exceptions import (
    DocumentInUseError,
    DocumentNotFoundError,
    InvalidUploadError,
    JobNotFoundError,
    JobNotRetryableError,
    ProductNotBoundError,
    UploadTooLargeError,
)
from .models import IngestionJob, KbDocument
from .repository import KbRepository
from .schemas import (
    ChunkItem,
    ChunkListResponse,
    DocumentDeleteResponse,
    IngestionJobItem,
    IngestionJobListResponse,
    KbDocumentItem,
    KbDocumentListResponse,
    KbUploadResponse,
    ProductKbStats,
    PurgeChunksResponse,
)

logger = get_logger(__name__)


def _relative(path: Path) -> str:
    try:
        return path.relative_to(APP_ROOT).as_posix()
    except ValueError:
        return str(path)


class KbService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = KbRepository(session)

    # ---------- 文档 ----------
    async def list_documents(
        self,
        *,
        product_id: int | None,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> KbDocumentListResponse:
        documents, total = await self.repository.list_documents(
            product_id=product_id,
            status=status,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        items = await self._build_document_items(documents)
        return KbDocumentListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    async def get_document(self, document_id: UUID) -> KbDocumentItem:
        document = await self.repository.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError
        items = await self._build_document_items([document])
        return items[0]

    async def upload(
        self,
        *,
        file: UploadFile,
        product_id: int,
        replace_document_id: UUID | None,
        apply_to_all: bool,
        force_full: bool,
        admin_id: int,
    ) -> KbUploadResponse:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise ProductNotFoundError

        data = await self._read_upload(file)
        original_filename = file.filename or "upload"

        try:
            new_stem, ext = build_storage_stem(original_filename)
            if ext == ".md":
                markdown_text = validate_markdown(data)
            else:
                validate_pdf(data)
        except StorageError as exc:
            raise InvalidUploadError(str(exc))

        md_dir = settings.storage.md_dir
        pdf_dir = settings.storage.pdf_dir

        if replace_document_id is not None:
            document = await self.repository.get_document(replace_document_id)
            if document is None:
                raise DocumentNotFoundError

            bound = await self.repository.bound_product_ids(document.clause_name)
            other_bound = [pid for pid in bound if pid != product_id]
            if other_bound and not apply_to_all:
                raise DocumentInUseError(
                    "该文档被其他产品共用，如需一并替换请勾选 apply_to_all"
                )

            storage_stem = document.storage_stem
            target_ids = set(bound) if apply_to_all else {product_id}
            target_ids.add(product_id)
        else:
            storage_stem = new_stem
            target_ids = {product_id}
            document = KbDocument()

        # 同一产品同时只允许一个活动任务; 必须在写盘前检查, 避免留下孤儿文件
        active = await self.repository.active_jobs_for_products(list(target_ids))
        if active:
            raise ProductHasActiveJobError

        clause_name = f"{storage_stem}{ext}"
        md_path = md_dir / f"{storage_stem}.md"
        pdf_path = pdf_dir / f"{storage_stem}.pdf"

        # 写盘: md 直接把内容写入; pdf 写原始文件并删除旧 md 以触发重新转换
        if ext == ".md":
            atomic_write_bytes(md_path, markdown_text.encode("utf-8"))
            source_path = md_path
            markdown_path = md_path
            document.status = "ready"
            document.conversion_error = None
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
        else:
            atomic_write_bytes(pdf_path, data)
            source_path = pdf_path
            markdown_path = md_path
            document.status = "converting"
            document.conversion_error = None
            if md_path.exists():
                md_path.unlink(missing_ok=True)

        document.storage_stem = storage_stem
        document.clause_name = clause_name
        document.original_filename = original_filename
        document.source_type = ext.lstrip(".")
        document.source_path = _relative(source_path)
        document.markdown_path = _relative(markdown_path)
        document.file_hash = hashlib.sha256(data).hexdigest()
        document.file_size = len(data)
        document.uploaded_by_admin_id = admin_id

        if document.id is None:
            self.session.add(document)

        await self.session.flush()

        products = {
            item.id: item
            for item in (
                await self.session.scalars(
                    select(Product).where(Product.id.in_(target_ids))
                )
            ).all()
        }

        jobs = [
            IngestionJob(
                product_id=pid,
                product_name=products[pid].name,
                document_id=document.id,
                clause_name=document.clause_name,
                source_type=document.source_type,
                source_path=document.source_path,
                status="pending",
                progress=0,
                force_full=force_full,
                admin_user_id=admin_id,
            )
            for pid in sorted(target_ids)
            if pid in products
        ]
        self.session.add_all(jobs)

        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ProductHasActiveJobError

        # UPDATE 后 updated_at 处于过期状态, 重新加载以避免同步 IO(MissingGreenlet)
        document = await self.repository.get_document(
            document.id, populate_existing=True
        )
        document_item = (await self._build_document_items([document]))[0]
        return KbUploadResponse(
            document=document_item,
            jobs=[IngestionJobItem.model_validate(job) for job in jobs],
        )

    async def delete_document(
        self, document_id: UUID, *, force: bool
    ) -> DocumentDeleteResponse:
        document = await self.repository.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError

        bound = await self.repository.bound_product_ids(document.clause_name)
        if bound and not force:
            raise DocumentInUseError(
                f"文档仍被 {len(bound)} 个产品绑定，请先解绑或传 force=true"
            )

        if bound and force:
            await self.session.execute(
                update(Product)
                .where(Product.id.in_(bound))
                .values(clause_name=None, status="inactive")
            )

        deleted_files = self._delete_files(document)
        await self.session.delete(document)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return DocumentDeleteResponse(
            deleted=True,
            deleted_files=deleted_files,
            unbound_product_ids=sorted(bound),
        )

    # ---------- 任务 ----------
    async def list_jobs(
        self,
        *,
        product_id: int | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> IngestionJobListResponse:
        jobs, total = await self.repository.list_jobs(
            product_id=product_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        return IngestionJobListResponse(
            items=[IngestionJobItem.model_validate(job) for job in jobs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_job(self, job_id: UUID) -> IngestionJobItem:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise JobNotFoundError
        return IngestionJobItem.model_validate(job)

    async def retry_job(self, job_id: UUID, *, force_full: bool) -> IngestionJobItem:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise JobNotFoundError
        if job.status not in ("failed", "cancelled"):
            raise JobNotRetryableError
        if job.product_id is None:
            raise ProductNotBoundError("原任务关联的产品已不存在")

        active = await self.repository.active_jobs_for_products([job.product_id])
        if active:
            raise ProductHasActiveJobError

        product = await self.session.get(Product, job.product_id)
        document = (
            await self.repository.get_document(job.document_id)
            if job.document_id is not None
            else None
        )
        clause_name = document.clause_name if document else job.clause_name
        if not clause_name:
            raise ProductNotBoundError

        new_job = IngestionJob(
            product_id=job.product_id,
            product_name=product.name if product else job.product_name,
            document_id=job.document_id,
            clause_name=clause_name,
            source_type=document.source_type if document else job.source_type,
            source_path=document.source_path if document else job.source_path,
            status="pending",
            progress=0,
            force_full=force_full,
            attempts=job.attempts + 1,
            admin_user_id=job.admin_user_id,
        )
        self.session.add(new_job)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ProductHasActiveJobError
        return IngestionJobItem.model_validate(new_job)

    async def reingest(
        self, product_id: int, *, force_full: bool, admin_id: int
    ) -> IngestionJobItem:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise ProductNotFoundError
        if not product.clause_name:
            raise ProductNotBoundError

        if await self.repository.active_jobs_for_products([product_id]):
            raise ProductHasActiveJobError

        document = await self.repository.find_document_by_clause_name(
            product.clause_name
        )
        source_type = (
            document.source_type
            if document
            else Path(product.clause_name).suffix.lstrip(".")
        )

        job = IngestionJob(
            product_id=product.id,
            product_name=product.name,
            document_id=document.id if document else None,
            clause_name=product.clause_name,
            source_type=source_type,
            source_path=document.source_path if document else None,
            status="pending",
            progress=0,
            force_full=force_full,
            admin_user_id=admin_id,
        )
        self.session.add(job)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ProductHasActiveJobError
        return IngestionJobItem.model_validate(job)

    # ---------- 产品知识块 ----------
    async def product_stats(self, product_id: int) -> ProductKbStats:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise ProductNotFoundError

        document = (
            await self.repository.find_document_by_clause_name(product.clause_name)
            if product.clause_name
            else None
        )
        active_jobs = await self.repository.active_jobs_for_products([product_id])
        has_markdown = bool(
            product.clause_name
            and (
                settings.storage.md_dir / f"{Path(product.clause_name).stem}.md"
            ).exists()
        )

        return ProductKbStats(
            product_id=product_id,
            chunk_count=await self.repository.count_chunks(product_id),
            text_count=await self.repository.count_chunks(product_id, "text"),
            table_count=await self.repository.count_chunks(product_id, "table"),
            published_count=await self.repository.count_chunks(product_id, published=True),
            candidate_count=await self.repository.count_chunks(product_id, published=False),
            has_markdown=has_markdown,
            document_id=document.id if document else None,
            document_status=document.status if document else None,
            active_job_id=active_jobs[0].id if active_jobs else None,
        )

    async def list_chunks(
        self,
        product_id: int,
        *,
        doc_type: str | None,
        include_content: bool,
        page: int,
        page_size: int,
    ) -> ChunkListResponse:
        chunks, total = await self.repository.list_chunks(
            product_id, doc_type=doc_type, page=page, page_size=page_size
        )
        items = [
            ChunkItem(
                id=chunk.id,
                section_path=chunk.section_path or [],
                doc_type=chunk.doc_type,
                chunk_index=chunk.chunk_index,
                content_hash=chunk.content_hash,
                content=chunk.content if include_content else (chunk.content or "")[:200],
                is_published=bool(chunk.is_published),
            )
            for chunk in chunks
        ]
        return ChunkListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    async def purge_chunks(self, product_id: int) -> PurgeChunksResponse:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise ProductNotFoundError
        result = await purge_product_knowledge(product_id)
        return PurgeChunksResponse(
            deleted_chunks=result["deleted_chunks"],
            deleted_vectors=result["deleted_vectors"],
            vector_error=result.get("vector_error"),
        )

    # ---------- 内部工具 ----------
    async def _build_document_items(
        self, documents: list[KbDocument]
    ) -> list[KbDocumentItem]:
        bound_map = await self.repository.bound_product_map(
            [document.clause_name for document in documents]
        )
        items = []
        for document in documents:
            item = KbDocumentItem.model_validate(document)
            item.bound_product_ids = sorted(
                bound_map.get(document.clause_name, [])
            )
            items.append(item)
        return items

    async def _read_upload(self, file: UploadFile) -> bytes:
        chunks: list[bytes] = []
        size = 0
        limit = settings.storage.max_upload_bytes
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise UploadTooLargeError(
                    f"上传文件不能超过 {settings.storage.max_upload_mb}MB"
                )
            chunks.append(chunk)
        await file.close()
        if size == 0:
            raise InvalidUploadError("上传文件为空")
        return b"".join(chunks)

    @staticmethod
    def _delete_files(document: KbDocument) -> int:
        deleted = 0
        root = settings.storage.root_path.resolve()
        for relative in {document.source_path, document.markdown_path}:
            if not relative:
                continue
            path = (APP_ROOT / relative).resolve()
            if not path.is_relative_to(root):
                logger.warning("拒绝删除存储目录之外的文件", path=str(path))
                continue
            try:
                if path.exists():
                    path.unlink()
                    deleted += 1
            except OSError as exc:
                logger.warning("删除文件失败", path=str(path), error=str(exc))
        return deleted

    # ---------- 版本发布管理 ----------

    async def publish_product_chunks(
        self,
        product_id: int,
        admin_id: int,
        admin_role: str = "kb",
        notes: str = "",
    ) -> dict:
        """发布产品全部候选知识块: is_published 置 true, 记录发布日志。

        验收要求(清单28): 知识运营岗位构建人不能发布自己的版本;
        admin(超级管理员)不受此限制, 可自行审核发布。
        """
        from sqlalchemy import update as sa_update
        from app.rag.models import KbRelease, ParentChunk

        # 检查是否有候选内容可发布
        candidate_count = await self.session.scalar(
            select(func.count()).select_from(ParentChunk).where(
                ParentChunk.product_id == product_id,
                ParentChunk.is_published == False,  # noqa: E712
            )
        )
        if not candidate_count:
            raise ValueError("没有待发布的候选知识块")

        # 查最近一次入库任务(记录构建人, 无论角色都要查)
        last_job = await self.session.scalar(
            select(IngestionJob)
            .where(IngestionJob.product_id == product_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )

        # kb 岗位: 禁止自己发自己的版本; admin(超级管理员)豁免
        if admin_role != "admin" and last_job and last_job.admin_user_id == admin_id:
            raise ValueError("构建人不能发布自己的版本, 请让其他管理员审核发布")

        # 批量发布
        await self.session.execute(
            sa_update(ParentChunk)
            .where(ParentChunk.product_id == product_id)
            .values(is_published=True)
        )

        # 记录发布日志
        release = KbRelease(
            product_id=product_id,
            status="published",
            created_by_admin_id=last_job.admin_user_id if last_job else None,
            published_by_admin_id=admin_id,
            published_at=func.now(),
            notes=notes,
        )
        self.session.add(release)
        await self.session.commit()
        return {"published_chunks": candidate_count, "release_id": release.id}

    async def retract_product_chunks(
        self,
        product_id: int,
        admin_id: int,
        notes: str = "",
    ) -> dict:
        """撤回产品全部已发布知识块: is_published 置 false, AI 不再检索到。"""
        from sqlalchemy import update as sa_update
        from app.rag.models import KbRelease, ParentChunk

        published_count = await self.session.scalar(
            select(func.count()).select_from(ParentChunk).where(
                ParentChunk.product_id == product_id,
                ParentChunk.is_published == True,  # noqa: E712
            )
        )
        if not published_count:
            raise ValueError("没有已发布的知识块可撤回")

        await self.session.execute(
            sa_update(ParentChunk)
            .where(ParentChunk.product_id == product_id)
            .values(is_published=False)
        )

        release = KbRelease(
            product_id=product_id,
            status="retracted",
            published_by_admin_id=admin_id,
            retracted_at=func.now(),
            notes=notes,
        )
        self.session.add(release)
        await self.session.commit()
        return {"retracted_chunks": published_count, "release_id": release.id}

    async def list_releases(self, product_id: int) -> list[dict]:
        """查看产品发布历史"""
        from app.rag.models import KbRelease

        releases = (
            await self.session.scalars(
                select(KbRelease)
                .where(KbRelease.product_id == product_id)
                .order_by(KbRelease.id.desc())
            )
        ).all()
        return [
            {
                "id": r.id,
                "product_id": r.product_id,
                "status": r.status,
                "created_by_admin_id": r.created_by_admin_id,
                "published_by_admin_id": r.published_by_admin_id,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "retracted_at": r.retracted_at.isoformat() if r.retracted_at else None,
                "notes": r.notes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in releases
        ]
