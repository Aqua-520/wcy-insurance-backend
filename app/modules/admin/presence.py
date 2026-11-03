"""客服在岗状态: 判断"此刻到底有没有人能接人工"。

为什么要这个: 营业时段是写在配置里的**声明**, 客服是不是坐在电脑前才是**事实**。
凌晨三点配成"在线"照样没人接, 反过来有人值夜班时按 9-21 挡掉也不合理。
所以转人工的主闸门用 last_seen_at(在线状态), 时段只用于文案提示。

实现: 后台每次接口鉴权通过时节流刷新 admin_users.last_seen_at(默认 30s 一次),
在线 = 最近 ONLINE_WINDOW_SECONDS 内有心跳。零新增接口, 打开后台就算在岗。
"""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AdminUser

# 超过这个秒数没有后台请求, 视为离线(前端轮询/心跳间隔 30s 足够)
ONLINE_WINDOW_SECONDS = 90
# 同一员工的 last_seen_at 最多每 30 秒写一次, 避免每个请求都 UPDATE
_TOUCH_INTERVAL_SECONDS = 30

_last_touch: dict[int, float] = {}

# 能接人工会话的岗位(知识运营不接会话)
HANDOFF_ROLES = ("cs", "admin")


def should_touch(admin_id: int) -> bool:
    """节流判断: 这个管理员这次请求要不要刷新 last_seen_at。"""
    now = time.monotonic()
    last = _last_touch.get(admin_id, 0.0)
    if now - last < _TOUCH_INTERVAL_SECONDS:
        return False
    _last_touch[admin_id] = now
    return True


async def touch(session: AsyncSession, admin: AdminUser) -> None:
    """刷新在线时间(调用方传入自己那次鉴权查询的短会话, 提交由调用方或本函数负责)。"""
    admin.last_seen_at = datetime.now(timezone.utc)
    await session.commit()


async def online_staff_count(session: AsyncSession) -> int:
    since = datetime.now(timezone.utc) - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AdminUser)
            .where(
                AdminUser.status == "active",
                AdminUser.role.in_(HANDOFF_ROLES),
                AdminUser.last_seen_at.is_not(None),
                AdminUser.last_seen_at >= since,
            )
        )
        or 0
    )


async def online_staff(session: AsyncSession) -> list[dict]:
    """在线客服清单(工作台/管理页展示用)。"""
    since = datetime.now(timezone.utc) - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    rows = (
        await session.execute(
            select(AdminUser.id, AdminUser.username, AdminUser.display_name, AdminUser.role, AdminUser.last_seen_at)
            .where(
                AdminUser.status == "active",
                AdminUser.role.in_(HANDOFF_ROLES),
                AdminUser.last_seen_at.is_not(None),
                AdminUser.last_seen_at >= since,
            )
            .order_by(AdminUser.last_seen_at.desc())
        )
    ).all()
    return [
        {
            "admin_id": int(row[0]),
            "username": row[1],
            "display_name": row[2],
            "role": row[3],
            "last_seen_at": row[4],
        }
        for row in rows
    ]
