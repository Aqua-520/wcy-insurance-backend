"""
知识库维护操作: 按产品清理 PostgreSQL 父块和 Milvus 向量。
"""
import asyncio

from sqlalchemy import delete

from app.core.logging import get_logger
from app.infra.database import AsyncSessionFactory

from .clients import close_vector_store, create_vector_store
from .models import ParentChunk

logger = get_logger(__name__)


async def purge_product_knowledge(
    product_id: int,
    *,
    purge_pg: bool = True,
    purge_vectors: bool = True,
) -> dict:
    """
    删除某产品的全部知识块和向量。

    - 使用 Milvus 表达式 product_id == X, 可同时清理 PG 中已丢失的孤儿向量;
    - 删除失败只记录日志并返回错误信息, 由调用方决定是否继续。
    """
    deleted_chunks = 0
    vector_deleted = False
    vector_error: str | None = None

    if purge_pg:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(ParentChunk).where(ParentChunk.product_id == product_id)
                )
                deleted_chunks = result.rowcount or 0

    if purge_vectors:
        vector_store = None
        try:
            vector_store = create_vector_store()
            await asyncio.to_thread(
                vector_store.delete, expr=f"product_id == {product_id}"
            )
            vector_deleted = True
        except Exception as exc:  # Milvus 未启动 / collection 不存在等
            vector_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "清理产品向量失败",
                product_id=product_id,
                error=vector_error,
            )
        finally:
            if vector_store is not None:
                await asyncio.to_thread(close_vector_store, vector_store)

    return {
        "deleted_chunks": deleted_chunks,
        "deleted_vectors": vector_deleted,
        "vector_error": vector_error,
    }
