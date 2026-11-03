"""人工接管(AI 转人工)数据库迁移 —— 幂等, 可重复执行。

做两件事:
1. chat_threads 增加状态机字段(create_all 不会改已有表, 必须显式 ALTER);
2. 新建 chat_messages(聊天消息业务真相源)。

用法: cd agent-service && .venv/Scripts/python script/migrate_handoff.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.infra.database import AsyncSessionFactory, engine  # noqa: E402

COLUMNS = [
    ("mode", "VARCHAR(20) NOT NULL DEFAULT 'ai'"),
    ("mode_changed_at", "TIMESTAMPTZ"),
    ("queue_at", "TIMESTAMPTZ"),
    ("claimed_by", "BIGINT"),
    ("claimed_at", "TIMESTAMPTZ"),
    ("agent_seen_at", "TIMESTAMPTZ"),
    ("ended_at", "TIMESTAMPTZ"),
    ("handoff_note", "TEXT NOT NULL DEFAULT ''"),
]

DDL = [
    # 1) 会话状态机
    *[
        f"ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS {name} {ddl}"
        for name, ddl in COLUMNS
    ],
    "CREATE INDEX IF NOT EXISTS ix_chat_threads_mode ON chat_threads (mode)",
    "COMMENT ON COLUMN chat_threads.mode IS '会话模式: ai / waiting / agent'",
    # 2) 消息真相源
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id BIGSERIAL PRIMARY KEY,
        thread_id UUID NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        message_type VARCHAR(30) NOT NULL DEFAULT 'text',
        sender_admin_id BIGINT,
        sender_admin_name VARCHAR(100),
        additional_info JSONB,
        client_msg_id VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_thread_id_id ON chat_messages (thread_id, id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client
        ON chat_messages (thread_id, client_msg_id)
        WHERE client_msg_id IS NOT NULL
    """,
    "COMMENT ON TABLE chat_messages IS '聊天消息表(业务真相源)'",
    "COMMENT ON COLUMN chat_messages.role IS 'user / assistant / agent / system'",
]


async def main() -> None:
    print(f"目标库: {settings.db.host}:{settings.db.port}/{settings.db.name}")
    async with engine.begin() as conn:
        for statement in DDL:
            await conn.execute(text(statement))
    print(f"DDL 执行完成: {len(DDL)} 条")

    async with AsyncSessionFactory() as session:
        cols = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='chat_threads' ORDER BY ordinal_position"
                )
            )
        ).scalars().all()
        print("chat_threads 列:", ", ".join(cols))
        msg_cols = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='chat_messages' ORDER BY ordinal_position"
                )
            )
        ).scalars().all()
        print("chat_messages 列:", ", ".join(msg_cols))
        total = await session.scalar(text("SELECT count(*) FROM chat_threads"))
        zero = await session.scalar(text("SELECT count(*) FROM chat_threads WHERE mode <> 'ai'"))
        mem = await session.scalar(text("SELECT count(*) FROM chat_messages"))
        print(f"会话总数={total}, 非 ai 态={zero}, 存量消息={mem}")


if __name__ == "__main__":
    asyncio.run(main())
