"""员工在岗状态字段迁移 —— 幂等。

admin_users 增加 last_seen_at: 后台每次鉴权通过节流刷新, 用于判断"有没有客服在线"。

用法: cd agent-service && .venv/Scripts/python script/migrate_presence.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.infra.database import AsyncSessionFactory, engine  # noqa: E402


async def main() -> None:
    print(f"目标库: {settings.db.host}:{settings.db.port}/{settings.db.name}")
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
        )
        await conn.execute(
            text(
                "COMMENT ON COLUMN admin_users.last_seen_at IS "
                "'最近活跃时间(后台接口鉴权时节流刷新), 判断客服是否在线'"
            )
        )
    async with AsyncSessionFactory() as session:
        cols = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='admin_users' ORDER BY ordinal_position"
                )
            )
        ).scalars().all()
        print("admin_users 列:", ", ".join(cols))
        rows = (
            await session.execute(
                text(
                    "SELECT id, username, role, status, last_seen_at FROM admin_users ORDER BY id LIMIT 10"
                )
            )
        ).all()
        for row in rows:
            print("  ", row)


if __name__ == "__main__":
    asyncio.run(main())
