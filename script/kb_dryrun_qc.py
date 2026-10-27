# -*- coding: utf-8 -*-
"""全量灌库前的纯切分质检：不连库、不调向量模型。遍历12个产品，输出块数/表格/超长/空块。"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\84370\Desktop\黑马-python阶段\python-project\wcy-insurance\agent-service")
sys.path.insert(0, str(ROOT))

from app.infra.database import AsyncSessionFactory, engine, close_database
engine.echo = False
from app.modules.product.repository import ProductRepository
from app.rag.splitter import split_clause, MAX_TEXT_CHARS
from app.rag.pipeline import RAGPipeline


async def main():
    async with AsyncSessionFactory() as session:
        products = await ProductRepository(session).get_product_list_repository(None)

    print(f"{'pid':>3} {'块数':>4} {'表':>3} {'空':>3} {'超1000':>6} {'min':>4} {'max':>5}  产品 / 条款")
    print("-" * 100)
    grand = {"chunks": 0, "tables": 0, "empty": 0, "over": 0}
    for p in products:
        stem = Path(p.clause_name).stem
        md = (ROOT / "data" / "raw" / "md" / f"{stem}.md").read_text(encoding="utf-8")
        chunks = split_clause(md, product_id=p.id, clause_stem=stem)
        texts = [c for c in chunks if c.doc_type == "text"]
        tables = [c for c in chunks if c.doc_type == "table"]
        empties = [c for c in chunks if not c.content.strip()]
        over = [c for c in texts if len(c.content) > MAX_TEXT_CHARS]
        lens = [len(c.content) for c in texts]
        grand["chunks"] += len(chunks)
        grand["tables"] += len(tables)
        grand["empty"] += len(empties)
        grand["over"] += len(over)
        print(f"{p.id:>3} {len(chunks):>4} {len(tables):>3} {len(empties):>3} {len(over):>6} "
              f"{min(lens):>4} {max(lens):>5}  {p.name[:18]} / {stem[:22]}")
    print("-" * 100)
    print(f"合计: {grand['chunks']} 块, 表格块 {grand['tables']}, 空块 {grand['empty']}(应0), 超1000字 {grand['over']}(应0)")
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
