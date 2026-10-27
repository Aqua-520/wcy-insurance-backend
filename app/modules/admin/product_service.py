"""
后台产品管理业务层
"""
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import APP_ROOT, settings
from app.core.logging import get_logger
from app.modules.kb.models import KbDocument
from app.modules.product.models import Product
from app.rag.maintenance import purge_product_knowledge

from .exceptions import (
    DocumentNotFoundError,
    ProductHasActiveJobError,
    ProductInUseError,
    ProductInvalidStateError,
    ProductNotFoundError,
    ProductValidationError,
)
from .product_repository import AdminProductRepository
from .product_schemas import (
    ProductAdminCreate,
    ProductAdminDetail,
    ProductAdminItem,
    ProductAdminListResponse,
    ProductAdminUpdate,
    ProductDeleteResponse,
)

logger = get_logger(__name__)

# 引用了 products(id) 的业务表; 有引用时禁止硬删除
REFERENCE_TABLES = (
    "rate_table_files",
    "rate_plans",
    "rate_table_items",
    "premium_quotes",
    "product_pricing_schemas",
    "product_pricing_bindings",
    "insurance_plan_items",
    "policies",
    "claims",
)

EDITABLE_FIELDS = (
    "name",
    "category",
    "insurer",
    "image_url",
    "description",
    "min_premium",
    "max_premium",
    "target_group",
    "highlights",
)


class AdminProductService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = AdminProductRepository(session)

    # ---------- 查询 ----------
    async def list_products(
        self,
        keyword: str | None,
        category: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> ProductAdminListResponse:
        products, total = await self.repository.list_products(
            keyword, category, status, page, page_size
        )
        ids = [product.id for product in products]
        chunk_map = await self.repository.chunk_counts(ids)
        job_map = await self.repository.active_jobs(ids)

        items = []
        for product in products:
            item = ProductAdminItem.model_validate(product)
            item.chunk_count = chunk_map.get(product.id, 0)
            item.active_job_id = job_map.get(product.id)
            items.append(item)

        return ProductAdminListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_detail(self, product_id: int) -> ProductAdminDetail:
        # 可能紧跟在 commit 之后调用, 必须从数据库重新加载过期字段
        product = await self.repository.get_product(
            product_id, populate_existing=True
        )
        if product is None:
            raise ProductNotFoundError

        chunk_map = await self.repository.chunk_counts([product_id])
        table_map = await self.repository.table_counts([product_id])
        job_map = await self.repository.active_jobs([product_id])
        document = await self._find_document(product.clause_name)

        has_markdown = bool(
            product.clause_name
            and self._markdown_path(product.clause_name).exists()
        )
        chunk_count = chunk_map.get(product_id, 0)

        base = ProductAdminItem.model_validate(product)
        detail = base.model_dump()
        detail.update(
            chunk_count=chunk_count,
            active_job_id=job_map.get(product_id),
            has_markdown=has_markdown,
            table_count=table_map.get(product_id, 0),
            document_id=document.id if document else None,
            document_status=document.status if document else None,
            needs_reingest=bool(product.clause_name)
            and (chunk_count == 0 or not has_markdown),
        )
        return ProductAdminDetail(**detail)

    # ---------- 写入 ----------
    async def create(self, data: ProductAdminCreate) -> ProductAdminDetail:
        clause_name = None
        if data.document_id is not None:
            document = await self._get_document(data.document_id)
            clause_name = document.clause_name

        product = Product(
            name=data.name,
            clause_name=clause_name,
            category=data.category,
            insurer=data.insurer,
            image_url=data.image_url,
            description=data.description,
            min_premium=data.min_premium,
            max_premium=data.max_premium,
            target_group=data.target_group,
            highlights=data.highlights,
            status="draft",
        )
        self.session.add(product)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_detail(product.id)

    async def update(self, product_id: int, data: ProductAdminUpdate) -> ProductAdminDetail:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise ProductNotFoundError

        fields = data.model_fields_set
        for field in EDITABLE_FIELDS:
            if field in fields:
                setattr(product, field, getattr(data, field))

        if "document_id" in fields:
            if data.document_id is None:
                product.clause_name = None
            else:
                document = await self._get_document(data.document_id)
                product.clause_name = document.clause_name

        if (
            product.min_premium is not None
            and product.max_premium is not None
            and product.min_premium > product.max_premium
        ):
            raise ProductValidationError("最低保费不能大于最高保费")

        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.get_detail(product.id)

    async def activate(self, product_id: int, allow_empty: bool) -> ProductAdminDetail:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise ProductNotFoundError
        if product.status == "active":
            return await self.get_detail(product_id)

        if not product.clause_name:
            raise ProductInvalidStateError("请先上传或绑定条款文件后再上架")
        if not self._markdown_path(product.clause_name).exists():
            raise ProductInvalidStateError("条款 Markdown 不存在，请重新上传或入库")

        chunk_count = await self.repository.count_chunks(product_id)
        if chunk_count == 0 and not allow_empty:
            raise ProductInvalidStateError("知识库尚未入库，请先上传条款并等待入库完成")

        product.status = "active"
        await self.session.commit()
        return await self.get_detail(product_id)

    async def deactivate(self, product_id: int) -> ProductAdminDetail:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise ProductNotFoundError
        if product.status != "inactive":
            product.status = "inactive"
            await self.session.commit()
        return await self.get_detail(product_id)

    async def delete(
        self,
        product_id: int,
        *,
        purge_kb: bool,
        purge_files: bool,
    ) -> ProductDeleteResponse:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise ProductNotFoundError

        active_jobs = await self.repository.active_jobs([product_id])
        if active_jobs:
            raise ProductHasActiveJobError

        references = await self._count_references(product_id)
        if references:
            detail = "、".join(f"{table}: {count}" for table, count in references.items())
            raise ProductInUseError(f"产品已被业务数据引用（{detail}），请改用下架")

        document = await self._find_document(product.clause_name)
        purge_result = {
            "deleted_chunks": 0,
            "deleted_vectors": False,
            "vector_error": None,
        }
        if purge_kb:
            purge_result = await purge_product_knowledge(product_id)

        try:
            await self.session.delete(product)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        deleted_files = 0
        if purge_files and document is not None:
            remaining = await self.session.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.clause_name == document.clause_name)
            )
            if not remaining:
                deleted_files = self._delete_document_files(document)
                try:
                    await self.session.delete(document)
                    await self.session.commit()
                except Exception:
                    await self.session.rollback()
                    logger.warning("删除知识库文档记录失败", document_id=str(document.id))

        return ProductDeleteResponse(
            deleted=True,
            deleted_chunks=purge_result["deleted_chunks"],
            deleted_vectors=purge_result["deleted_vectors"],
            vector_error=purge_result.get("vector_error"),
            deleted_files=deleted_files,
        )

    # ---------- 内部工具 ----------
    async def _get_document(self, document_id) -> KbDocument:
        document = await self.session.get(KbDocument, document_id)
        if document is None:
            raise DocumentNotFoundError
        return document

    async def _find_document(self, clause_name: str | None) -> KbDocument | None:
        if not clause_name:
            return None
        return await self.session.scalar(
            select(KbDocument).where(KbDocument.clause_name == clause_name)
        )

    @staticmethod
    def _markdown_path(clause_name: str) -> Path:
        return settings.storage.md_dir / f"{Path(clause_name).stem}.md"

    async def _count_references(self, product_id: int) -> dict[str, int]:
        existing_rows = await self.session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        existing = set(existing_rows.scalars().all())

        references: dict[str, int] = {}
        for table in REFERENCE_TABLES:
            if table not in existing:
                continue
            count = await self.session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE product_id = :product_id"),
                {"product_id": product_id},
            )
            if count:
                references[table] = int(count)
        return references

    @staticmethod
    def _delete_document_files(document: KbDocument) -> int:
        """删除文档对应的 md/pdf 文件, 只允许删除存储根目录内的文件"""
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
