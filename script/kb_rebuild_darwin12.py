# -*- coding: utf-8 -*-
"""
升级点2 端到端：重建两库 -> 只灌达尔文12号(product_id=2) -> 连跑两遍验证增量
-> 真实向量探针检索。会删除旧 parent_chunks 表和旧 Milvus collection（已获用户确认）。
跑法：.venv/Scripts/python kb_rebuild_darwin12.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\84370\Desktop\黑马-python阶段\python-project\wcy-insurance\agent-service")
sys.path.insert(0, str(ROOT))

from langchain_milvus import BM25BuiltInFunction, Milvus
from langchain_ollama import OllamaEmbeddings
from pymilvus import connections, utility

from app.core.config import settings
from app.common.models import Base
from app.infra.database import engine, AsyncSessionFactory, close_database

engine.echo = False  # 自测时关掉 SQL 日志噪音

# 导入模型以注册表到 Base.metadata
from app.rag.models import ParentChunk  # noqa: F401
from app.rag.pipeline import RAGPipeline
from app.rag.retriever import QuestionChunkRetriever
from app.modules.product.repository import ProductRepository

COLLECTION = "insurance_collection"
PRODUCT_ID = 2


def make_store() -> Milvus:
    emb = OllamaEmbeddings(model="qwen3-embedding:0.6b", dimensions=1024)
    return Milvus(
        embedding_function=emb,
        collection_name=COLLECTION,
        builtin_function=BM25BuiltInFunction(analyzer_params={"type": "chinese"}),
        vector_field=["dense", "sparse"],
        connection_args={"uri": settings.rag.milvus_url},
        auto_id=False,
    )


async def recreate_pg_table() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=[ParentChunk.__table__])
        )
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[ParentChunk.__table__])
        )
    print("[PG] parent_chunks 已按新结构重建")


def drop_milvus_collection() -> None:
    connections.connect(alias="rebuild", uri=settings.rag.milvus_url)
    if utility.has_collection(COLLECTION, using="rebuild"):
        utility.drop_collection(COLLECTION, using="rebuild")
        print(f"[Milvus] 旧 collection {COLLECTION} 已删除")
    else:
        print(f"[Milvus] collection {COLLECTION} 不存在，跳过删除")


async def get_product(pid: int):
    async with AsyncSessionFactory() as session:
        repo = ProductRepository(session)
        products = await repo.get_product_list_repository(None)
        return next(p for p in products if p.id == pid)


async def pg_count(pid: int) -> int:
    import psycopg
    with psycopg.connect(settings.db.checkpoint_url) as c:
        cur = c.cursor()
        cur.execute("SELECT count(*), sum((doc_type='table')::int) FROM parent_chunks WHERE product_id=%s", (pid,))
        total, tables = cur.fetchone()
        cur.execute("SELECT count(DISTINCT content_hash), count(*) FROM parent_chunks WHERE product_id=%s", (pid,))
        distinct_hash, _ = cur.fetchone()
    return total, tables, distinct_hash


async def main():
    # 0) 重建两库
    await recreate_pg_table()
    drop_milvus_collection()

    store = make_store()

    # 0.1) 先探活本机 ollama embedding
    v = store.embedding_func.embed_query("等待期是多少天")
    print(f"[Ollama] embedding 探活 ok，维度={len(v)}")

    pipeline = RAGPipeline(store)
    product = await get_product(PRODUCT_ID)
    print(f"[产品] {product.id} {product.name} <- {product.clause_name}")

    # 1) 第一遍入库（应全是 added）
    r1 = await pipeline.product_info_to_store(product)
    print("[第一遍]", dict(r1))

    total, tables, distinct_hash = await pg_count(PRODUCT_ID)
    print(f"[校验] PG 块数={total} 表格块={tables} 指纹去重数={distinct_hash}")
    from pymilvus import Collection as PmCollection
    pmcol = PmCollection(COLLECTION, using="rebuild")
    pmcol.load()
    print(f"[校验] Milvus 实体数={pmcol.num_entities}")
    print("Milvus schema 字段:", [f.name for f in pmcol.schema.fields])

    # 2) 第二遍入库（应 added=0 changed=0 deleted=0 unchanged=total）
    r2 = await pipeline.product_info_to_store(product)
    print("[第二遍(验证增量)]", dict(r2))
    ok_idem = r2["added"] == 0 and r2["changed"] == 0 and r2["deleted"] == 0 and r2["unchanged"] == r1["total"]
    print("幂等(第二遍全跳过):", "✅" if ok_idem else "❌")

    # 3) 真实向量探针：表格类 / 定义类问题
    retriever = QuestionChunkRetriever(store)
    probes = ["等待期是多少天", "重大疾病保险金有哪些责任，必选还是可选", "什么是犹豫期"]
    print("\n[探针检索] product_id=2 top_k=3")
    for q in probes:
        parents = await retriever.retrieve(question=q, product_id=PRODUCT_ID, top_k=3)
        print(f"\n问: {q}  命中 {len(parents)} 块")
        for p in parents:
            tag = "表" if p.doc_type == "table" else "文"
            head = p.content.replace("\n", " ")[:60]
            print(f"   [{tag}] {' > '.join(p.section_path)[:34]} | {head}")

    store.client.close()
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
