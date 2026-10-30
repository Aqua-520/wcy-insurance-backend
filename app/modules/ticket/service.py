"""
工单业务层

状态机:
    pending --客服领取--> processing --客服关闭--> closed --客户不认可重新打开--> reopened
    reopened --客服再次领取--> processing
未领取(pending/reopened)的工单客服不能回复; 客户确认关闭才真正静默。
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .exceptions import TicketForbiddenError, TicketInvalidStateError, TicketNotFoundError
from .models import Ticket, TicketMessage


def _ticket_no() -> str:
    """生成受理编号: T + 日期 + 4位随机, 如 T20261029-A1B2"""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"T{day}-{secrets.token_hex(2).upper()}"


class TicketService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 客户侧 ----------

    async def create_from_user(
        self, user_id: int, ticket_type: str, summary: str, thread_id: str | None = None
    ) -> Ticket:
        """客户主动发起工单(投诉/理赔咨询/人工)"""
        ticket = Ticket(
            ticket_no=_ticket_no(),
            user_id=user_id,
            thread_id=thread_id,
            ticket_type=ticket_type,
            status="pending",
            summary=summary,
        )
        self.session.add(ticket)
        # 请求级 session 不会自动提交, 必须显式 commit 否则请求结束即回滚
        await self.session.commit()
        return ticket

    async def create_from_ai(
        self, user_id: int, ticket_type: str, summary: str, thread_id: str | None = None
    ) -> Ticket:
        """AI 转人工节点调用: 同会话已有未关闭工单则复用, 不重复开单"""
        existing = await self.session.scalar(
            select(Ticket).where(
                Ticket.user_id == user_id,
                Ticket.thread_id == thread_id,
                Ticket.ticket_type == ticket_type,
                Ticket.status.in_(("pending", "processing", "reopened")),
            )
        )
        if existing is not None:
            return existing
        return await self.create_from_user(user_id, ticket_type, summary, thread_id)

    async def list_by_user(self, user_id: int) -> list[Ticket]:
        return list(
            await self.session.scalars(
                select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.id.desc())
            )
        )

    async def get_owned_by_user(self, ticket_id: int, user_id: int) -> Ticket:
        ticket = await self.session.get(Ticket, ticket_id)
        # 不暴露他人工单是否存在, 统一按"不存在"处理
        if ticket is None or ticket.user_id != user_id:
            raise TicketNotFoundError
        return ticket

    async def add_customer_message(self, ticket: Ticket, content: str) -> TicketMessage:
        if ticket.status == "closed":
            raise TicketInvalidStateError("工单已关闭，如需继续处理请先重新打开")
        message = TicketMessage(ticket_id=ticket.id, sender_role="customer", content=content)
        self.session.add(message)
        await self.session.commit()
        return message

    async def reopen(self, ticket: Ticket) -> Ticket:
        """客户不认可关闭结果, 重新打开回灌"""
        if ticket.status != "closed":
            raise TicketInvalidStateError("只有已关闭的工单可以重新打开")
        ticket.status = "reopened"
        ticket.assigned_admin_id = None
        await self.session.commit()
        return ticket

    # ---------- 客服侧 ----------

    async def list_for_staff(
        self, status: str | None = None, ticket_type: str | None = None
    ) -> tuple[list[Ticket], int]:
        query = select(Ticket)
        count_query = select(func.count()).select_from(Ticket)
        if status:
            query = query.where(Ticket.status == status)
            count_query = count_query.where(Ticket.status == status)
        if ticket_type:
            query = query.where(Ticket.ticket_type == ticket_type)
            count_query = count_query.where(Ticket.ticket_type == ticket_type)
        total = (await self.session.execute(count_query)).scalar_one()
        tickets = list(await self.session.scalars(query.order_by(Ticket.id.desc())))
        return tickets, total

    async def get_for_staff(self, ticket_id: int) -> Ticket:
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError
        return ticket

    async def claim(self, ticket: Ticket, admin_id: int) -> Ticket:
        """客服领取: 只有待领取/重新打开的可领取"""
        if ticket.status not in ("pending", "reopened"):
            raise TicketInvalidStateError("该工单已被领取或已关闭")
        ticket.status = "processing"
        ticket.assigned_admin_id = admin_id
        await self.session.commit()
        return ticket

    async def reply(self, ticket: Ticket, admin_id: int, content: str) -> TicketMessage:
        # 未领取不能回复: 只有本人领取的处理中工单可以回复
        if ticket.status not in ("processing",):
            raise TicketInvalidStateError("请先领取工单再回复")
        if ticket.assigned_admin_id != admin_id:
            raise TicketForbiddenError
        message = TicketMessage(
            ticket_id=ticket.id, sender_role="staff", admin_id=admin_id, content=content
        )
        self.session.add(message)
        await self.session.commit()
        return message

    async def close(self, ticket: Ticket, admin_id: int) -> Ticket:
        """客服关闭: 需已领取; 客户不认可可重新打开"""
        if ticket.status != "processing" or ticket.assigned_admin_id != admin_id:
            raise TicketInvalidStateError("请先领取该工单再关闭")
        ticket.status = "closed"
        ticket.closed_at = datetime.now(timezone.utc).isoformat()
        await self.session.commit()
        return ticket

    async def get_detail(self, ticket_id: int) -> Ticket:
        ticket = await self.session.scalar(
            select(Ticket)
            .options(selectinload(Ticket.messages))
            .where(Ticket.id == ticket_id)
        )
        if ticket is None:
            raise TicketNotFoundError
        return ticket
