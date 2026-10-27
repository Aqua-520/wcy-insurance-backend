"""
后台产品管理数据访问层
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kb.models import IngestionJob
from app.modules.product.models import Product
from app.rag.models import ParentChunk

ACTIVE_JOB_STATUSES = ("pending", "processing")


class AdminProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _conditions(
        self,
        keyword: str | None,
        category: str | None,
        status: str | None,
    ) -> list:
        conditions = []
        if keyword:
            conditions.append(Product.name.ilike(f"%{keyword.strip()}%"))
        if category:
            conditions.append(Product.category == category)
        if status and status != "all":
            conditions.append(Product.status == status)
        return conditions

    async def list_products(
        self,
        keyword: str | None,
        category: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Product], int]:
        stmt = select(Product).where(*self._conditions(keyword, category, status))
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        rows = await self.session.scalars(
            stmt.order_by(Product.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def get_product(
        self, product_id: int, *, populate_existing: bool = False
    ) -> Product | None:
        # 写入后立即读取时需要强制刷新: onupdate=func.now() 会让 updated_at
        # 在 commit 后处于过期状态, 直接访问会触发同步 IO(MissingGreenlet)
        return await self.session.get(
            Product, product_id, populate_existing=populate_existing
        )

    async def chunk_counts(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        rows = await self.session.execute(
            select(ParentChunk.product_id, func.count())
            .where(ParentChunk.product_id.in_(product_ids))
            .group_by(ParentChunk.product_id)
        )
        return {row[0]: int(row[1]) for row in rows.all()}

    async def table_counts(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        rows = await self.session.execute(
            select(ParentChunk.product_id, func.count())
            .where(
                ParentChunk.product_id.in_(product_ids),
                ParentChunk.doc_type == "table",
            )
            .group_by(ParentChunk.product_id)
        )
        return {row[0]: int(row[1]) for row in rows.all()}

    async def active_jobs(self, product_ids: list[int]) -> dict[int, UUID]:
        if not product_ids:
            return {}
        rows = await self.session.execute(
            select(IngestionJob.product_id, IngestionJob.id).where(
                IngestionJob.product_id.in_(product_ids),
                IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        return {row[0]: row[1] for row in rows.all() if row[0] is not None}

    async def count_chunks(self, product_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ParentChunk)
                .where(ParentChunk.product_id == product_id)
            )
            or 0
        )
