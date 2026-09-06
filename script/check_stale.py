"""验证 Milvus 中是否存在指向已删除父块的陈旧子块"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from app.infra.database import AsyncSessionFactory
from app.rag import vector_store


async def main():
    pid = 1

    # 1. postgres 中该产品的父块 id 集合
    async with AsyncSessionFactory() as session:
        pg_ids = set(
            str(r[0]) for r in (await session.execute(
                text("SELECT id FROM parent_chunks WHERE product_id = :p"), {"p": pid}
            )).all()
        )
    print(f"postgres 中 product {pid} 的父块数: {len(pg_ids)}")

    # 2. Milvus 中该产品的全部子块的 parent_id（query 不分页，先取 1000 条足够说明问题）
    rows = vector_store.client.query(
        collection_name=vector_store.collection_name,
        filter=f"product_id == {pid}",
        output_fields=["parent_id"],
        limit=1000,
    )
    milvus_parent_ids = [r["parent_id"] for r in rows]
    milvus_distinct = set(milvus_parent_ids)
    print(f"Milvus 中 product {pid} 的子块数: {len(milvus_parent_ids)}，去重 parent_id 数: {len(milvus_distinct)}")

    stale = milvus_distinct - pg_ids
    fresh = milvus_distinct & pg_ids
    print(f"  其中 parent_id 在 postgres 中【不存在】的(陈旧): {len(stale)}")
    print(f"  其中 parent_id 在 postgres 中【存在】的(有效): {len(fresh)}")

    stale_chunk_count = sum(1 for x in milvus_parent_ids if x in stale)
    print(f"  陈旧子块条数: {stale_chunk_count} / {len(milvus_parent_ids)} "
          f"({stale_chunk_count / max(len(milvus_parent_ids),1):.0%} 的检索结果会命中死链)")


if __name__ == "__main__":
    asyncio.run(main())
