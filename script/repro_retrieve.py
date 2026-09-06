"""临时复现脚本：直接调用 question_retriever.retrieve 抓取真实异常"""
import asyncio
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from app.infra.database import AsyncSessionFactory
from app.rag import question_retriever


async def main():
    # 先从 postgre 找一个确实有父块切片的 product_id
    async with AsyncSessionFactory() as session:
        rows = (await session.execute(
            text("SELECT product_id, count(*) FROM parent_chunks GROUP BY product_id LIMIT 5")
        )).all()
        print("parent_chunks 里的 product_id:", rows)

    if not rows:
        print("parent_chunks 表为空，无法复现")
        return

    product_id = rows[0][0]
    print(f"使用 product_id={product_id} 调用 retrieve ...")

    try:
        result = await question_retriever.retrieve(
            question="这个保险的等待期是多久？",
            product_id=product_id,
        )
        print("检索成功, 片段数:", len(result))
        for r in result:
            print("-", r.section_path, "|", r.content[:60].replace("\n", " "))
    except Exception as e:
        print("!! 检索失败:", type(e).__name__, e)
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
