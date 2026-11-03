"""人工接管业务层。

状态机(chat_threads.mode):
    ai --客户点转人工--> waiting --客服接入--> agent --客服结束--> ai
    waiting --客户取消--> ai

铁律:
- 排队态(waiting)AI 仍可回答: 客户不能干等;
- 接管态(agent)AI 静默: 客户消息只落库+广播, 不调模型;
- 抢单必须原子(条件 UPDATE), 两个客服同时点只有一个成功;
- 客服结束会话必须填交接说明, AI 恢复时读这一句, 不塞客服原话(承诺转移风险)。
"""
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.admin.models import AdminUser
from app.modules.admin.presence import online_staff_count
from app.modules.auth.models import User
from app.modules.chat_thread.broadcaster import broadcaster
from app.modules.chat_thread.exceptions import ChatThreadNotFoundError
from app.modules.chat_thread.models import ChatMessage, ChatThread
from app.modules.chat_thread.repository import ChatThreadRepository, _as_uuid as as_uuid

from .exceptions import (
    HandoffInvalidStateError,
    SessionAlreadyClaimedError,
    SessionNotClaimedError,
    SessionNotFoundError,
)

logger = get_logger(__name__)

# 人工接管态
MODE_AI = "ai"
MODE_WAITING = "waiting"
MODE_AGENT = "agent"

# 排队预估: 每位前面的人按 90 秒算(纯估算, 文案必须写"预计")
EST_SECONDS_PER_SESSION = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seconds_since(start: datetime | None) -> int:
    if start is None:
        return 0
    return max(0, int((_now() - start).total_seconds()))


def is_off_hours() -> bool:
    """当前是否处于客服休息时段(默认 00:00-06:00 没人上班)。

    支持跨零点(如 22-6); 起止相同视为 7x24 没有休息时段。
    只用于文案区分"客服已休息"和"客服暂时不在线", 不参与放行判断。
    """
    cfg = settings.handoff
    hour = datetime.now().hour
    start, end = cfg.offline_start_hour, cfg.offline_end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # 跨零点: 22:00-06:00
    return hour >= start or hour < end


class HandoffService:
    def __init__(self, session: AsyncSession, agent=None):
        self.session = session
        self.agent = agent
        self.repository = ChatThreadRepository(session)

    # ---------- 内部工具 ----------

    async def _get_thread(self, thread_id) -> ChatThread:
        thread = await self.session.get(ChatThread, as_uuid(thread_id))
        if thread is None:
            raise SessionNotFoundError
        return thread

    async def _get_owned_thread(self, thread_id, user_id: int) -> ChatThread:
        thread = await self.repository.get_chat_thread_owner_repository(thread_id, user_id)
        if thread is None:
            raise ChatThreadNotFoundError
        return thread

    async def _add_message(
        self,
        thread_id,
        role: str,
        content: str,
        *,
        message_type: str = "text",
        sender_admin_id: int | None = None,
        sender_admin_name: str | None = None,
        additional_info: dict | None = None,
    ) -> ChatMessage:
        message = await self.repository.add_message(
            thread_id=thread_id,
            role=role,
            content=content,
            message_type=message_type,
            sender_admin_id=sender_admin_id,
            sender_admin_name=sender_admin_name,
            additional_info=additional_info,
        )
        broadcaster.publish(
            str(thread_id),
            {
                "type": "new_message",
                "thread_id": str(thread_id),
                "message_id": message.id,
                "role": role,
            },
        )
        return message

    async def _admin_name(self, admin_id: int | None) -> str | None:
        if not admin_id:
            return None
        return await self.session.scalar(
            select(func.coalesce(AdminUser.display_name, AdminUser.username)).where(
                AdminUser.id == admin_id
            )
        )

    async def _queue_position(self, thread: ChatThread) -> int:
        """排队位次: 比我更早进入 waiting 的还有几个 + 1。"""
        if thread.mode != MODE_WAITING or thread.queue_at is None:
            return 0
        ahead = await self.session.scalar(
            select(func.count())
            .select_from(ChatThread)
            .where(
                ChatThread.mode == MODE_WAITING,
                ChatThread.queue_at.is_not(None),
                ChatThread.queue_at < thread.queue_at,
            )
        )
        return int(ahead or 0) + 1

    async def maybe_expire(self, thread: ChatThread) -> bool:
        """兜底: 排队超时 / 客服静默超时 -> 自动转回 AI。

        凌晨没人接、客服下班或掉线, 都不能让客户卡在"等人工"里干等。
        转人工只是通道切换, 不产生工单; 留痕靠会话里的 system 消息。
        读接口(增量拉取/历史/队列)时惰性触发, 不依赖后台任务, 行为确定可测。
        """
        cfg = settings.handoff
        now = _now()

        if thread.mode == MODE_WAITING and thread.queue_at is not None:
            waited = (now - thread.queue_at).total_seconds()
            # 排队中客服全下线: 不再让客户等 3 分钟, 15 秒就给结论
            online = await online_staff_count(self.session)
            timeout = cfg.wait_timeout_seconds if online > 0 else min(cfg.wait_timeout_seconds, 15)
            if waited >= timeout:
                thread.mode = MODE_AI
                thread.queue_at = None
                thread.mode_changed_at = now
                await self._add_message(
                    thread.id,
                    "system",
                    "暂时没有客服可以接入，已为你转回 AI 继续解答；需要人工可以稍后再试",
                    message_type="handoff_notice",
                )
                await self.session.commit()
                broadcaster.publish(str(thread.id), {"type": "mode_changed", "mode": MODE_AI})
                logger.info("排队超时自动转回 AI thread=%s 等待=%ss", thread.id, int(waited))
                return True

        if thread.mode == MODE_AGENT:
            last_seen = thread.agent_seen_at or thread.claimed_at
            if last_seen is not None and (now - last_seen).total_seconds() >= cfg.agent_idle_timeout_seconds:
                thread.mode = MODE_AI
                thread.claimed_by = None
                thread.claimed_at = None
                thread.agent_seen_at = None
                thread.queue_at = None
                thread.mode_changed_at = now
                await self._add_message(
                    thread.id,
                    "system",
                    "客服暂时离开，已为你转回 AI；如需人工可以再次申请",
                    message_type="handoff_notice",
                )
                await self.session.commit()
                broadcaster.publish(str(thread.id), {"type": "mode_changed", "mode": MODE_AI})
                logger.info("客服静默超时自动释放 thread=%s", thread.id)
                return True

        return False

    # ---------- 客户侧 ----------

    async def request_handoff(self, user_id: int, thread_id, system_notice: bool = True) -> dict:
        """客户申请转人工: 只切会话状态(排队/接管), 不建工单。

        转人工是**同步通道**, 工单是**异步业务单据**(投诉/理赔), 两者别混:
        没有通知渠道时给客户一个受理编号, 第二天没人翻, 只是多一条僵尸数据。
        system_notice=False 用于"聊天里说转人工": 由 AI 回复承载文案。
        """
        thread = await self._get_owned_thread(thread_id, user_id)

        if thread.mode == MODE_AGENT:
            name = await self._admin_name(thread.claimed_by)
            return {
                "thread_id": thread.id,
                "mode": MODE_AGENT,
                "queue_position": 0,
                "est_wait_seconds": 0,
                "notice": f"客服 {name or ''} 正在与你沟通" if name else "客服正在与你沟通",
                "claimed_by_name": name,
            }

        if thread.mode == MODE_WAITING:
            position = await self._queue_position(thread)
            return {
                "thread_id": thread.id,
                "mode": MODE_WAITING,
                "queue_position": position,
                "est_wait_seconds": max(30, (position - 1) * EST_SECONDS_PER_SESSION),
                "notice": "已在排队中, AI 可以继续为你解答",
            }

        # 主闸门: 此刻有没有客服在线。没人在线就直说, 不排队也不留单
        online = await online_staff_count(self.session)
        if online == 0:
            return await self._offline_notice(thread, system_notice=system_notice)

        thread.mode = MODE_WAITING
        thread.queue_at = _now()
        thread.mode_changed_at = _now()
        thread.claimed_by = None
        thread.claimed_at = None
        await self.session.commit()
        await self.session.refresh(thread)

        position = await self._queue_position(thread)
        notice = (
            f"正在为你转接人工客服, 前面还有 {position - 1} 位, 预计等待 "
            f"{max(30, (position - 1) * EST_SECONDS_PER_SESSION)} 秒; 期间 AI 可以继续为你解答"
        )
        if is_off_hours():
            notice += f"（当前为休息时段 {settings.handoff.off_hours_text}，仍有客服在线）"
        if system_notice:
            await self._add_message(thread.id, "system", notice, message_type="handoff_notice")
            await self.session.commit()
        broadcaster.publish(str(thread.id), {"type": "mode_changed", "mode": MODE_WAITING})

        return {
            "thread_id": thread.id,
            "mode": MODE_WAITING,
            "queue_position": position,
            "est_wait_seconds": max(30, (position - 1) * EST_SECONDS_PER_SESSION),
            "notice": notice,
        }

    async def cancel_handoff(self, user_id: int, thread_id) -> dict:
        """客户随时可以「切回 AI」: 排队中取消, 或接管中主动结束人工。

        真实的客服系统必须给客户这个出口 —— 客服可能只回了半句就不动了,
        客户不能因此被锁死在"AI 静默"里。
        """
        thread = await self._get_owned_thread(thread_id, user_id)
        if thread.mode == MODE_AI:
            raise HandoffInvalidStateError("当前就是 AI 服务")

        was_agent = thread.mode == MODE_AGENT
        agent_name = await self._admin_name(thread.claimed_by) if was_agent else None

        thread.mode = MODE_AI
        thread.queue_at = None
        thread.claimed_by = None
        thread.claimed_at = None
        thread.agent_seen_at = None
        thread.ended_at = _now()
        if was_agent:
            thread.handoff_note = thread.handoff_note or "客户主动结束人工服务"
        thread.mode_changed_at = _now()
        await self.session.commit()
        await self.session.refresh(thread)

        text = (
            "客户已结束人工服务，转回 AI 继续为你解答"
            if was_agent
            else "已取消人工服务请求，继续由 AI 为你服务"
        )
        await self._add_message(thread.id, "system", text, message_type="handoff_notice")
        await self.session.commit()
        broadcaster.publish(str(thread.id), {"type": "mode_changed", "mode": MODE_AI})
        return {
            "thread_id": thread.id,
            "mode": MODE_AI,
            "notice": text + (f"（{agent_name} 已退出）" if agent_name else ""),
        }

    async def _offline_notice(self, thread: ChatThread, system_notice: bool = True) -> dict:
        """此刻没有客服在线: 直接告诉客户, 不排队、不留单、不改状态。

        没有通知渠道的"留言工单"是假闭环(客户拿到编号也等不到回音),
        所以要诚实告知: 要么继续问 AI, 要么工作时间再来。
        """
        if is_off_hours():
            notice = (
                f"现在是客服休息时段（{settings.handoff.off_hours_text}），暂时没有人工客服在线。"
                "你可以继续把问题告诉我，我会尽力回答；需要人工的话，请在工作时间再来。"
            )
        else:
            notice = (
                "当前没有人工客服在线。"
                "你可以继续把问题告诉我，我会尽力回答；稍后也可以再申请人工。"
            )
        if system_notice:
            await self._add_message(thread.id, "system", notice, message_type="handoff_notice")
            await self.session.commit()
        return {
            "thread_id": thread.id,
            "mode": MODE_AI,
            "queue_position": 0,
            "est_wait_seconds": 0,
            "notice": notice,
            "offline": True,
        }

    async def incremental_messages(self, user_id: int, thread_id, after_id: int = 0, limit: int = 100) -> dict:
        """客户侧增量拉取(正文真相源): 先校验会话归属。"""
        thread = await self._get_owned_thread(thread_id, user_id)
        # 惰性兜底: 排队/客服静默超时就地转回 AI, 客户下一次轮询就能感知
        await self.maybe_expire(thread)
        rows = await self.repository.list_messages(thread.id, after_id=after_id, limit=limit + 1)
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "thread_id": thread.id,
            "mode": thread.mode or MODE_AI,
            "items": [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content or "",
                    "message_type": row.message_type or "text",
                    "sender_admin_name": row.sender_admin_name,
                    "additional_info": row.additional_info,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
            "last_id": rows[-1].id if rows else after_id,
            "has_more": has_more,
        }

    # ---------- 客服侧 ----------

    async def staff_messages(self, thread_id, after_id: int = 0, limit: int = 100) -> dict:
        """客服侧读某个会话的消息(工作台右侧对话流, 不校验归属只校验岗位)。"""
        thread = await self._get_thread(thread_id)
        await self.maybe_expire(thread)
        rows = await self.repository.list_messages(thread.id, after_id=after_id, limit=limit + 1)
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "thread_id": thread.id,
            "mode": thread.mode or MODE_AI,
            "items": [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content or "",
                    "message_type": row.message_type or "text",
                    "sender_admin_name": row.sender_admin_name,
                    "additional_info": row.additional_info,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
            "last_id": rows[-1].id if rows else after_id,
            "has_more": has_more,
        }

    async def list_sessions(self, modes: tuple[str, ...], admin_id: int | None = None) -> dict:
        """会话队列: 等待中的排前面(按等待时长), 我接管的固定排最前。"""
        threads = list(
            (
                await self.session.scalars(
                    select(ChatThread)
                    .where(ChatThread.mode.in_(modes))
                    .order_by(ChatThread.queue_at.asc().nulls_last(), ChatThread.mode_changed_at.asc())
                    .limit(100)
                )
            ).all()
        )
        # 惰性兜底: 超时会话不再挂在工作台(客户那边也已转回 AI)
        expired = [thread for thread in threads if await self.maybe_expire(thread)]
        if expired:
            threads = [thread for thread in threads if thread.mode in modes]
        thread_ids = [thread.id for thread in threads]

        # 客户名
        user_ids = {thread.user_id for thread in threads}
        customer_map: dict[int, str] = {}
        if user_ids:
            rows = (
                await self.session.execute(
                    select(User.id, func.coalesce(User.display_name, User.username)).where(
                        User.id.in_(user_ids)
                    )
                )
            ).all()
            customer_map = {int(uid): name for uid, name in rows}

        # 最后一条正文消息
        last_map: dict[str, ChatMessage] = {}
        if thread_ids:
            rows = list(
                (
                    await self.session.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.thread_id.in_(thread_ids))
                        .order_by(ChatMessage.id.desc())
                        .limit(len(thread_ids) * 5)
                    )
                ).all()
            )
            for row in rows:
                last_map.setdefault(str(row.thread_id), row)

        items = []
        for thread in threads:
            key = str(thread.id)
            last = last_map.get(key)
            pending_since = thread.claimed_at or thread.queue_at
            unread_start = await self._unread_since(thread.id, pending_since)
            items.append(
                {
                    "thread_id": key,
                    "user_id": thread.user_id,
                    "customer_name": customer_map.get(thread.user_id, f"客户{thread.user_id}"),
                    "title": thread.title,
                    "mode": thread.mode,
                    "waiting_seconds": _seconds_since(thread.queue_at if thread.mode == MODE_WAITING else thread.claimed_at),
                    "claimed_by": thread.claimed_by,
                    "claimed_by_name": await self._admin_name(thread.claimed_by),
                    "last_message": (last.content or "")[:120] if last else "",
                    "last_message_role": last.role if last else "",
                    "last_message_at": last.created_at if last else None,
                    "unread": unread_start,
                }
            )

        # 我接管的排最前, 其余保持等待时长顺序
        if admin_id is not None:
            items.sort(key=lambda item: (0 if item["claimed_by"] == admin_id else 1, -item["waiting_seconds"]))

        return {
            "items": items,
            "total": len(items),
            "waiting": sum(1 for item in items if item["mode"] == MODE_WAITING),
            "mine": sum(1 for item in items if item["claimed_by"] == admin_id) if admin_id else 0,
            # 当前在线客服数(90 秒内有后台请求): 为 0 时客户转人工会直接走留言
            "online": await online_staff_count(self.session),
        }

    async def _unread_since(self, thread_id, since: datetime | None) -> int:
        """未读计数: since 之后客户发了几条。since 为空(纯排队)则算全部客户消息。"""
        conditions = [
            ChatMessage.thread_id == as_uuid(thread_id),
            ChatMessage.role == "user",
        ]
        if since is not None:
            conditions.append(ChatMessage.created_at >= since)
        return int(
            await self.session.scalar(
                select(func.count()).select_from(ChatMessage).where(*conditions)
            )
            or 0
        )

    async def claim(self, thread_id, admin_id: int, admin_name: str | None = None) -> dict:
        """抢单: 原子条件 UPDATE, 抢不到返回 409。"""
        thread = await self._get_thread(thread_id)
        if thread.mode == MODE_AGENT:
            if thread.claimed_by == admin_id:
                return {"thread_id": thread.id, "mode": MODE_AGENT, "claimed_by_name": await self._admin_name(admin_id)}
            raise SessionAlreadyClaimedError
        if thread.mode != MODE_WAITING:
            raise HandoffInvalidStateError("该会话不在排队中")

        claimed = await self.repository.claim_thread(thread.id, admin_id)
        if not claimed:
            await self.session.rollback()
            raise SessionAlreadyClaimedError
        await self.session.commit()

        name = admin_name or await self._admin_name(admin_id) or f"客服{admin_id}"

        await self._add_message(
            thread.id,
            "system",
            f"{name} 已接入人工服务, 接下来由真人客服为你解答",
            message_type="handoff_notice",
            sender_admin_id=admin_id,
            sender_admin_name=name,
        )
        await self.session.commit()
        broadcaster.publish(
            str(thread.id),
            {"type": "mode_changed", "mode": MODE_AGENT, "claimed_by_name": name},
        )
        return {"thread_id": thread.id, "mode": MODE_AGENT, "claimed_by_name": name}

    async def send_agent_message(self, thread_id, admin_id: int, admin_name: str | None, content: str) -> dict:
        thread = await self._get_thread(thread_id)
        if thread.mode != MODE_AGENT:
            raise HandoffInvalidStateError("请先接入会话再回复")
        if thread.claimed_by != admin_id:
            raise SessionNotClaimedError

        name = admin_name or await self._admin_name(admin_id) or f"客服{admin_id}"
        message = await self._add_message(
            thread.id,
            "agent",
            content.strip(),
            sender_admin_id=admin_id,
            sender_admin_name=name,
        )
        # 有动作就是"在场", 静默超时重新计时
        thread.agent_seen_at = _now()
        await self.session.commit()
        return {
            "id": message.id,
            "thread_id": str(thread.id),
            "role": "agent",
            "content": message.content,
            "sender_admin_name": name,
            "created_at": message.created_at,
        }

    async def heartbeat(self, thread_id, admin_id: int) -> dict:
        """客服工作台心跳: 证明"人还在", 避免静默超时被自动释放。"""
        thread = await self._get_thread(thread_id)
        if thread.mode != MODE_AGENT or thread.claimed_by != admin_id:
            return {"accepted": False, "mode": thread.mode}
        thread.agent_seen_at = _now()
        await self.session.commit()
        return {
            "accepted": True,
            "mode": thread.mode,
            "idle_timeout_seconds": settings.handoff.agent_idle_timeout_seconds,
        }

    async def end_session(self, thread_id, admin_id: int, note: str) -> dict:
        """客服结束会话: 回 AI + 关工单 + 注入交接说明(不注入客服原话)。"""
        thread = await self._get_thread(thread_id)
        if thread.mode != MODE_AGENT:
            raise HandoffInvalidStateError("该会话不在人工接管中")
        if thread.claimed_by != admin_id:
            raise SessionNotClaimedError

        name = await self._admin_name(admin_id) or f"客服{admin_id}"
        note = note.strip()

        thread.mode = MODE_AI
        thread.mode_changed_at = _now()
        thread.ended_at = _now()
        thread.handoff_note = note
        thread.queue_at = None
        # 结束即释放接管人, 否则下次 claim 的 "claimed_by IS NULL" 条件会把会话锁死
        thread.claimed_by = None
        thread.claimed_at = None
        await self.session.commit()
        await self.session.refresh(thread)

        await self._add_message(
            thread.id,
            "system",
            f"{name} 的人工服务已结束, 继续由 AI 为你服务",
            message_type="handoff_notice",
        )
        await self.session.commit()
        broadcaster.publish(str(thread.id), {"type": "mode_changed", "mode": MODE_AI})

        injected, detail = await self._inject_ai_resume(thread.id, note)
        return {
            "thread_id": thread.id,
            "mode": MODE_AI,
            "handoff_note": note,
            "ai_resume_injected": injected,
            "detail": detail,
        }

    async def _inject_ai_resume(self, thread_id, note: str) -> tuple[bool, str]:
        """把交接说明注入图状态, 让 AI 接着上文回答。

        只注入一句摘要, 绝不注入客服原话(客服的承诺不能变成 AI 的承诺)。
        注入失败不影响会话恢复(只是 AI 会少一段上下文), 只记日志。
        """
        if self.agent is None:
            return False, "agent 未就绪, 跳过上下文注入"
        try:
            config = RunnableConfig(configurable={"thread_id": str(thread_id)})
            await self.agent.aupdate_state(
                config=config,
                values={
                    "messages": [
                        AIMessage(
                            content=f"[人工客服已处理完毕] 交接说明: {note}。以下继续由 AI 为你服务。"
                        )
                    ]
                },
            )
            return True, "交接说明已注入 AI 上下文"
        except Exception as exc:  # noqa: BLE001
            logger.exception("交接说明注入失败 thread=%s", thread_id)
            return False, f"注入失败: {type(exc).__name__}"
