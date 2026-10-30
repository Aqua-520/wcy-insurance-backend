"""
知识库管理数据访问层
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.product.models import Product
from app.rag.models import ParentChunk

from .models import IngestionJob, KbDocument

ACTIVE_JOB_STATUSES = ("pending", "processing")


class KbRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 文档 ----------
    async def list_documents(
        self,
        *,
        product_id: int | None,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[KbDocument], int]:
        conditions = []
        if product_id is not None:
            conditions.append(
                KbDocument.clause_name.in_(
                    select(Product.clause_name).where(Product.id == product_id)
                )
            )
        if status:
            conditions.append(KbDocument.status == status)
        if keyword:
            conditions.append(KbDocument.original_filename.ilike(f"%{keyword.strip()}%"))

        stmt = select(KbDocument).where(*conditions)
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        rows = await self.session.scalars(
            stmt.order_by(KbDocument.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def get_document(
        self, document_id: UUID, *, populate_existing: bool = False
    ) -> KbDocument | None:
        return await self.session.get(
            KbDocument, document_id, populate_existing=populate_existing
        )

    async def find_document_by_clause_name(self, clause_name: str) -> KbDocument | None:
        return await self.session.scalar(
            select(KbDocument).where(KbDocument.clause_name == clause_name)
        )

    async def bound_product_ids(self, clause_name: str) -> list[int]:
        rows = await self.session.scalars(
            select(Product.id).where(Product.clause_name == clause_name)
        )
        return list(rows.all())

    async def bound_product_map(self, clause_names: list[str]) -> dict[str, list[int]]:
        if not clause_names:
            return {}
        rows = await self.session.execute(
            select(Product.clause_name, Product.id).where(
                Product.clause_name.in_(clause_names)
            )
        )
        result: dict[str, list[int]] = {}
        for clause_name, product_id in rows.all():
            result.setdefault(clause_name, []).append(product_id)
        return result

    # ---------- 任务 ----------
    async def list_jobs(
        self,
        *,
        product_id: int | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[IngestionJob], int]:
        conditions = []
        if product_id is not None:
            conditions.append(IngestionJob.product_id == product_id)
        if status:
            conditions.append(IngestionJob.status == status)

        stmt = select(IngestionJob).where(*conditions)
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        rows = await self.session.scalars(
            stmt.order_by(IngestionJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def get_job(self, job_id: UUID) -> IngestionJob | None:
        return await self.session.get(IngestionJob, job_id)

    async def active_jobs_for_products(self, product_ids: list[int]) -> list[IngestionJob]:
        if not product_ids:
            return []
        rows = await self.session.scalars(
            select(IngestionJob).where(
                IngestionJob.product_id.in_(product_ids),
                IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        return list(rows.all())

    # ---------- 产品知识块 ----------
    async def count_chunks(
        self,
        product_id: int,
        doc_type: str | None = None,
        published: bool | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ParentChunk).where(
            ParentChunk.product_id == product_id
        )
        if doc_type:
            stmt = stmt.where(ParentChunk.doc_type == doc_type)
        if published is not None:
            stmt = stmt.where(ParentChunk.is_published == published)
        return int(await self.session.scalar(stmt) or 0)

    async def list_chunks(
        self,
        product_id: int,
        *,
        doc_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ParentChunk], int]:
        conditions = [ParentChunk.product_id == product_id]
        if doc_type:
            conditions.append(ParentChunk.doc_type == doc_type)

        stmt = select(ParentChunk).where(*conditions)
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        rows = await self.session.scalars(
            stmt.order_by(ParentChunk.chunk_index.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)
