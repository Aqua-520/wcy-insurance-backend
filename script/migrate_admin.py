"""
后台管理 schema 迁移（幂等，可重复执行）。

用途:
1. 创建 admin_users / kb_documents / ingestion_jobs 三张新表;
2. 修复 parent_chunks 与部署 SQL 的结构漂移(chunk_index/content_hash/doc_type/visibility);
3. 放开 products.clause_name 的非空约束, 支持草稿产品;
4. 把现有产品的条款文件回填为 kb_documents 档案。

运行(在 agent-service 目录):
    .venv/Scripts/python script/migrate_admin.py
"""
import asyncio
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import APP_ROOT, settings
# 导入全部 ORM 模型, 让 Base.metadata 知道要建哪些表
from app.common.models import Base
from app.infra.database import AsyncSessionFactory, close_database, engine
from app.modules.admin.models import AdminUser  # noqa: F401
from app.modules.auth.models import User  # noqa: F401  tickets.user_id 外键需要
from app.modules.intent.models import ApplicationIntent  # noqa: F401
from app.modules.kb.models import IngestionJob, KbDocument  # noqa: F401
from app.modules.product.models import Product
from app.modules.ticket.models import Ticket, TicketMessage  # noqa: F401
from app.rag.models import KbRelease, ParentChunk  # noqa: F401

ALTER_STATEMENTS = [
    # parent_chunks 结构漂移修复
    "ALTER TABLE parent_chunks ADD COLUMN IF NOT EXISTS chunk_index BIGINT NOT NULL DEFAULT 1",
    "ALTER TABLE parent_chunks ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE parent_chunks ADD COLUMN IF NOT EXISTS doc_type VARCHAR(20) NOT NULL DEFAULT 'text'",
    "ALTER TABLE parent_chunks ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'public'",
    "CREATE INDEX IF NOT EXISTS idx_parent_chunks_product_hash ON parent_chunks(product_id, content_hash)",
    # 草稿产品
    "ALTER TABLE products ALTER COLUMN clause_name DROP NOT NULL",
    # 岗位角色: admin(管理员) / cs(客服) / kb(知识运营)
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(30) NOT NULL DEFAULT 'admin'",
    # 知识库发布状态: false=候选(未发布), true=已发布(AI可检索)
    "ALTER TABLE parent_chunks ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS idx_parent_chunks_published ON parent_chunks(is_published)",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _backfill_documents(session) -> tuple[int, int]:
    """从 products.clause_name 回填 kb_documents, 按 stem 去重。"""
    products = (
        await session.scalars(
            select(Product).where(Product.clause_name.is_not(None)).order_by(Product.id)
        )
    ).all()

    inserted = 0
    skipped = 0
    seen: set[str] = set()

    for product in products:
        clause_name = product.clause_name
        if not clause_name:
            continue
        stem = Path(clause_name).stem
        if stem in seen:
            continue
        seen.add(stem)

        md_path = APP_ROOT / "data" / "raw" / "md" / f"{stem}.md"
        pdf_path = APP_ROOT / "data" / "raw" / "kb" / f"{stem}.pdf"

        if not md_path.exists() and not pdf_path.exists():
            print(f"[跳过] 条款文件不存在: {stem}")
            skipped += 1
            continue

        if pdf_path.exists():
            source_type = "pdf"
            source_file = pdf_path
            stored_clause_name = f"{stem}.pdf"
        else:
            source_type = "md"
            source_file = md_path
            stored_clause_name = f"{stem}.md"

        values = {
            "storage_stem": stem,
            "clause_name": stored_clause_name,
            "original_filename": Path(clause_name).name,
            "source_type": source_type,
            "source_path": source_file.relative_to(APP_ROOT).as_posix(),
            "markdown_path": md_path.relative_to(APP_ROOT).as_posix(),
            "file_hash": _sha256(source_file),
            "file_size": source_file.stat().st_size,
            "status": "ready" if md_path.exists() else "conversion_failed",
        }
        stmt = (
            pg_insert(KbDocument)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["storage_stem"])
            .returning(KbDocument.id)
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            inserted += 1

    return inserted, skipped


async def main() -> None:
    # 1. 建缺失的新表(不修改已存在的表)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in ALTER_STATEMENTS:
            await connection.execute(text(statement))

    print("新表与结构检查完成 ✅")

    # 2. 回填 kb_documents
    async with AsyncSessionFactory() as session:
        async with session.begin():
            inserted, skipped = await _backfill_documents(session)
        document_count = await session.scalar(
            select(func.count()).select_from(KbDocument)
        )

    # 3. 输出检查结果
    async with engine.connect() as connection:
        chunk_columns = (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'parent_chunks' ORDER BY ordinal_position"
                )
            )
        ).scalars().all()

    print(f"parent_chunks 列: {', '.join(chunk_columns)}")
    print(f"kb_documents: 新增 {inserted} 条, 跳过 {skipped} 条, 当前共 {document_count} 条")
    print("迁移完成 ✅")
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
