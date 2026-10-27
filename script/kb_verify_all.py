# -*- coding: utf-8 -*-
"""全量灌库后的终检：两库计数/跨产品隔离/各险种探针/抽样幂等。"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\84370\Desktop\黑马-python阶段\python-project\wcy-insurance\agent-service")
sys.path.insert(0, str(ROOT))

import psycopg
from pymilvus import Collection, connections
from langchain_milvus import BM25BuiltInFunction, Milvus
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings
from app.infra.database import AsyncSessionFactory, engine, close_database
engine.echo = False
from app.modules.product.repository import ProductRepository
from app.rag.pipeline import RAGPipeline
from app.rag.retriever import QuestionChunkRetriever

COLLECTION = "insurance_collection"
EXPECTED = {1: 352, 2: 264, 3: 262, 4: 54, 5: 54, 6: 299, 7: 60, 8: 68, 9: 21, 10: 27, 11: 27, 12: 37}


def make_store():
    return Milvus(
        embedding_function=OllamaEmbeddings(model="qwen3-embedding:0.6b", dimensions=1024),
        collection_name=COLLECTION,
        builtin_function=BM25BuiltInFunction(analyzer_params={"type": "chinese"}),
        vector_field=["dense", "sparse"],
        connection_args={"uri": settings.rag.milvus_url},
        auto_id=False,
    )


async def main():
    # 1) PG 计数
    with psycopg.connect(settings.db.checkpoint_url) as c:
        cur = c.cursor()
        cur.execute("SELECT product_id, count(*), sum((doc_type='table')::int) FROM parent_chunks GROUP BY product_id ORDER BY product_id")
        pg = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("SELECT count(*), count(DISTINCT id) FROM parent_chunks")
        total, distinct_id = cur.fetchone()
    print(f"[PG] 总块数={total} 主键去重={distinct_id} 表格块合计={sum(v[1] for v in pg.values())}")
    print("[PG] 每产品与干切期望比对:",
          "✅ 全一致" if all(pg.get(pid, (0,))[0] == n for pid, n in EXPECTED.items()) else "❌ " + str(pg))

    # 2) Milvus 计数/唯一/标签
    connections.connect(alias="v", uri=settings.rag.milvus_url)
    col = Collection(COLLECTION, using="v")
    col.flush(); col.load()
    print(f"[Milvus] flush 后实体数={col.num_entities} (期望1525)")
    rows = col.query(expr="product_id >= 1", output_fields=["pk", "product_id", "doc_type"], limit=2000)
    pks = [r["pk"] for r in rows]
    print(f"[Milvus] 取出={len(rows)} 主键唯一={'✅' if len(set(pks)) == len(pks) else '❌'} "
          f"表格块={sum(1 for r in rows if r['doc_type']=='table')}(期望24) 与PG总数一致={'✅' if len(rows)==total else '❌'}")

    # 3) 各险种真实探针
    store = make_store()
    retriever = QuestionChunkRetriever(store)
    probes = [
        (2, "等待期是多少天"),
        (6, "免赔额怎么扣除，一般医疗保险金报哪些"),
        (10, "意外身故或伤残保险金怎么赔"),
        (4, "长期住院医疗保险责任有哪些"),
        (8, "身故保险金怎么给付"),
    ]
    print("\n[探针] 各险种 top3：")
    for pid, q in probes:
        parents = await retriever.retrieve(question=q, product_id=pid, top_k=3)
        same = all(p.product_id == pid for p in parents)
        print(f"\npid={pid} 问:{q}  命中{len(parents)}块 跨产品隔离={'✅' if same else '❌串产品'}")
        for p in parents:
            tag = "表" if p.doc_type == "table" else "文"
            print(f"   [{tag}] {' > '.join(p.section_path)[:40]} | {p.content[:48].replace(chr(10),' ')}")

    # 4) 跨产品隔离强测：用达尔文特有的“责任清单表”问题去查意外险，绝不能命中达尔文表格
    parents = await retriever.retrieve(question="首次重大疾病保险金必选还是可选 责任清单", product_id=10, top_k=5)
    leak = [p for p in parents if p.product_id != 10]
    print(f"\n[隔离强测] 用重疾表问题查意外险(pid10)，串到其他产品的块数={len(leak)} {'✅' if not leak else '❌'}")

    # 5) 抽样幂等：对 1/6/10 再入库，应全部 unchanged
    async with AsyncSessionFactory() as session:
        products = await ProductRepository(session).get_product_list_repository(None)
    pmap = {p.id: p for p in products}
    pipeline = RAGPipeline(store)
    print("\n[抽样幂等] 对 pid 1/6/10 再跑一遍：")
    for pid in (1, 6, 10):
        r = await pipeline.product_info_to_store(pmap[pid])
        ok = r["added"] == 0 and r["changed"] == 0 and r["deleted"] == 0 and r["unchanged"] == r["total"]
        print(f"   pid={pid}: {dict((k, r[k]) for k in ('total','added','changed','unchanged','deleted'))} {'✅' if ok else '❌'}")

    store.client.close()
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
