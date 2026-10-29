"""
统一人工工单模型。

投诉、高风险问题、客户明确要求人工、理赔咨询都进这一张工单表,
由 AI 转人工节点或客户主动发起创建, 客服岗位在后台领取处理。
工单号对客户展示, 是受理编号。
"""
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class Ticket(Base, CreateAtMixin, UpdateAtMixin):
    """人工服务工单"""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_no: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="受理编号, 对客户展示"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="发起工单的客户",
    )
    # 关联的咨询会话, 便于客服查看脱敏轨迹(有则存)
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 工单类型: handoff(转人工) / complaint(投诉) / claim(理赔咨询)
    ticket_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'handoff'::character varying"),
        comment="工单类型: handoff / complaint / claim",
    )
    # pending 待领取 / processing 处理中 / closed 已关闭 / reopened 已重新打开
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'pending'::character varying"),
        index=True,
        comment="工单状态: pending / processing / closed / reopened",
    )
    # 客户诉求摘要, 转人工节点把用户原话存进来
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 领取该工单的客服
    assigned_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="领取工单的客服",
    )
    closed_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", order_by="TicketMessage.id", cascade="all, delete-orphan"
    )


class TicketMessage(Base, CreateAtMixin):
    """工单沟通记录: 客户补充与客服回复"""

    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # customer / staff
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    # 客服回复时记 admin id, 客户补充时为空
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")
