"""
清理 Milvus 中的陈旧子块:
重新入库时 postgres 父块被删旧重建(UUID 重新生成),而 Milvus 旧子块未删除,
这些子块的 parent_id 指向已不存在的父块,形成死链。本脚本按产品扫描并删除之。
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Windows GBK 控制台无法打印 emoji 日志,强制 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text
from app.infra.database import AsyncSessionFactory
from app.rag import vector_store

BATCH = 100


async def main():
    # 1. 收集 postgres 中每个产品的有效父块 id
    async with AsyncSessionFactory() as session:
        rows = (await session.execute(
            text("SELECT product_id, id FROM parent_chunks")
        )).all()
    pg_ids: dict[int, set[str]] = {}
    for product_id, chunk_id in rows:
        pg_ids.setdefault(product_id, set()).add(str(chunk_id))
    print(f"postgres 中有父块数据的产品: {sorted(pg_ids)}")

    # 2. 逐产品扫描 Milvus,找出死链子块的主键
    total_deleted = 0
    for product_id, valid_parent_ids in pg_ids.items():
        milvus_rows = vector_store.client.query(
            collection_name=vector_store.collection_name,
            filter=f"product_id == {product_id}",
            output_fields=["pk", "parent_id"],
            limit=16384,
        )
        stale_pks = [
            r["pk"] for r in milvus_rows
            if r["parent_id"] not in valid_parent_ids
        ]
        print(f"product {product_id}: milvus子块 {len(milvus_rows)} 条, 死链 {len(stale_pks)} 条")

        # 3. 分批按主键删除
        for i in range(0, len(stale_pks), BATCH):
            vector_store.delete(ids=stale_pks[i:i + BATCH])
        total_deleted += len(stale_pks)

    print(f"清理完成,共删除陈旧子块 {total_deleted} 条")


if __name__ == "__main__":
    asyncio.run(main())
