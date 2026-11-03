"""人工接管数据一致性巡检 —— 找出"会话状态和工单状态对不上"的脏数据。

检查项:
  A. handoff 工单还挂着(pending/processing), 但对应会话已经回到 ai(或会话已被删)
  B. 同一个会话存在多张未关闭的 handoff 工单(重复开单)
  C. 消息指向不存在的会话(chat_messages 孤儿)
  D. 会话卡在 waiting/agent 但早已超时(静默释放没跑到)

默认只报告; 加 --fix 会把 A 类工单关闭(A 是纯粹的账面不一致, 安全)。
B/C 不自动删: 涉及历史与审计, 人工确认后再处理。

用法:
  .venv/Scripts/python script/check_handoff_consistency.py          # 只报告
  .venv/Scripts/python script/check_handoff_consistency.py --fix    # 顺手修 A
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.infra.database import AsyncSessionFactory, engine  # noqa: E402

# DB_ECHO=True 时 SQL 会把报告埋掉; 必须在引擎创建之后再关日志
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)

FIX = "--fix" in sys.argv

A_SQL = """
SELECT t.id, t.ticket_no, t.status, t.assigned_admin_id, t.thread_id,
       th.mode AS thread_mode, t.created_at
FROM tickets t
LEFT JOIN chat_threads th ON th.id::text = t.thread_id
WHERE t.ticket_type = 'handoff'
  AND t.status IN ('pending', 'processing', 'reopened')
  AND (th.id IS NULL OR th.mode = 'ai')
ORDER BY t.id
"""

B_SQL = """
SELECT thread_id, count(*) AS open_count
FROM tickets
WHERE ticket_type = 'handoff' AND status IN ('pending', 'processing', 'reopened')
  AND thread_id IS NOT NULL
GROUP BY thread_id
HAVING count(*) > 1
ORDER BY open_count DESC
"""

C_SQL = """
SELECT m.id, m.thread_id, left(m.content, 30)
FROM chat_messages m
LEFT JOIN chat_threads t ON t.id = m.thread_id
WHERE t.id IS NULL
ORDER BY m.id
"""

D_SQL = """
SELECT id, title, mode, queue_at, claimed_at, agent_seen_at,
       now() - coalesce(agent_seen_at, claimed_at, queue_at) AS idle
FROM chat_threads
WHERE mode IN ('waiting', 'agent')
ORDER BY idle DESC NULLS LAST
"""


async def main() -> None:
    print(f"库: {settings.db.host}:{settings.db.port}/{settings.db.name}  (fix={FIX})\n")
    async with AsyncSessionFactory() as session:
        a_rows = (await session.execute(text(A_SQL))).all()
        b_rows = (await session.execute(text(B_SQL))).all()
        c_rows = (await session.execute(text(C_SQL))).all()
        d_rows = (await session.execute(text(D_SQL))).all()

        print(f"[A] 会话已回 ai 但工单未关闭: {len(a_rows)} 条")
        for row in a_rows:
            print(f"    ticket={row[1]} status={row[2]} assigned={row[3]} "
                  f"thread={row[4]} thread_mode={row[5]} created={row[6]}")

        print(f"[B] 同一会话多张未关闭 handoff 单: {len(b_rows)} 组")
        for row in b_rows:
            print(f"    thread={row[0]} 打开中={row[1]} 张")

        print(f"[C] 消息孤儿(指向已删会话): {len(c_rows)} 条")
        for row in c_rows:
            print(f"    msg_id={row[0]} thread={row[1]} 内容={row[2]}")

        print(f"[D] 仍在 waiting/agent 的会话: {len(d_rows)} 个(超时会在下次读取时自动结算)")
        for row in d_rows:
            print(f"    thread={row[0]} mode={row[2]} 静默={row[6]} title={row[1]}")

        if FIX and a_rows:
            ids = [row[0] for row in a_rows]
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE tickets SET status = 'closed', closed_at = now(), "
                        "updated_at = now() WHERE id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            print(f"\n已修复 A 类: 关闭 {len(ids)} 张工单 {ids}")
        elif a_rows:
            print("\n提示: 加 --fix 可关闭 A 类工单(纯账面不一致)")


if __name__ == "__main__":
    asyncio.run(main())
