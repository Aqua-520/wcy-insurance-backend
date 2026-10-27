# 导入数据模型
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ParentChunk


class ParentChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # —— 升级点3：增量入库 ——
    async def get_chunk_map(self, product_id: int) -> dict[UUID, str]:
        """
        取某产品现有全部块的 {确定性主键id: content_hash}。
        供入库时比对指纹，判断“不变/变化/消失”。
        """
        rows = await self.session.execute(
            select(ParentChunk.id, ParentChunk.content_hash).where(
                ParentChunk.product_id == product_id
            )
        )
        return {row[0]: row[1] for row in rows.all()}

    async def upsert_chunks(self, chunks: list[ParentChunk]) -> None:
        """按确定性主键批量 upsert：不存在插入，存在则更新内容与指纹。"""
        if not chunks:
            return
        payload = [
            {
                "id": c.id,
                "product_id": c.product_id,
                "clause_name": c.clause_name,
                "section_path": c.section_path,
                "content": c.content,
                "chunk_index": c.chunk_index,
                "content_hash": c.content_hash,
                "doc_type": c.doc_type,
                "visibility": c.visibility,
            }
            for c in chunks
        ]
        stmt = pg_insert(ParentChunk).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "clause_name": stmt.excluded.clause_name,
                "section_path": stmt.excluded.section_path,
                "content": stmt.excluded.content,
                "chunk_index": stmt.excluded.chunk_index,
                "content_hash": stmt.excluded.content_hash,
                "doc_type": stmt.excluded.doc_type,
                "visibility": stmt.excluded.visibility,
            },
        )
        await self.session.execute(stmt)

    async def delete_by_ids(self, ids: list[UUID]) -> None:
        """删除本次切分里已不存在的块（内容被删/章节被并块）。"""
        if not ids:
            return
        await self.session.execute(delete(ParentChunk).where(ParentChunk.id.in_(ids)))

    async def delete_parent_chunks(self, product_id: int) -> None:
        """删除某产品的全部父块（全量重建时用）。"""
        await self.session.execute(
            delete(ParentChunk).where(ParentChunk.product_id == product_id)
        )

    # 根据子块保存的所属父块id,查询到父块的内容
    async def find_by_parent_id(self, parent_ids: list[str]) -> list[ParentChunk]:
        """
        向量检索命中后，按父块主键回 PG 取完整内容。
        :param parent_ids: 父块主键（uuid 字符串）
        :return: 数据库查询结果列表对象
        """
        if not parent_ids:
            return []
        result = await self.session.scalars(
            select(ParentChunk).where(ParentChunk.id.in_(parent_ids))
        )
        return list(result.all())