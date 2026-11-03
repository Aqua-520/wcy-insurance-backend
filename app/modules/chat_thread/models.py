"""
存放后端与数据库交互的表数据模型类
基于类对表字段做映射

2026-11-02 人工接管(AI 转人工)升级:
- chat_threads 增加会话状态机字段(mode/claimed_by/handoff_note 等)
- 新增 chat_messages: 聊天消息的业务真相源。
  升级前消息只存在 LangGraph checkpointer 里(aget_state 全量快照),
  无法增量拉取/标未读/让客服消息与 AI 消息同列, 所以单独建表。
  checkpointer 只服务 AI 推理, 前端渲染与客服工作台一律读这张表。
"""

from datetime import datetime
from uuid import UUID ,uuid4

from sqlalchemy import BigInteger, DateTime, String, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as DB_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class ChatThread(Base, CreateAtMixin, UpdateAtMixin):
    __tablename__ = "chat_threads"
    __table_args__ = (
        Index("ix_chat_threads_user_id", "user_id"),
        {"comment": "聊天会话表"},
    )

    # 使用uuid作为主键
    id: Mapped[UUID] = mapped_column(
        DB_UUID(as_uuid=True),
        primary_key=True,
        # 自动化生成
        default=uuid4,
        comment="会话ID",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="用户ID",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        server_default="新会话",
        comment="会话标题",
    )

    # ---------- 人工接管状态机 ----------
    # ai: AI 全权应答 / waiting: 已申请转人工, AI 仍可应答(排队) / agent: 客服接管, AI 静默
    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'ai'::character varying"),
        index=True,
        comment="会话模式: ai / waiting / agent",
    )
    mode_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="状态最近变更时间"
    )
    queue_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="进入排队的时间(排队位次依据)"
    )
    claimed_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="接管客服 admin_users.id"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="客服接入时间"
    )
    agent_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="客服最近活跃时间(心跳/发消息), 静默超时据此自动释放回 AI",
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="人工服务结束时间"
    )
    handoff_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("''::text"),
        comment="客服结束会话时填写的交接说明(AI 恢复回答的上下文)",
    )
    # created_at 和 updated_at 由 Mixin 提供（请确保 Mixin 有定义）

    def __repr__(self) -> str:
        return f"<ChatThread(id={self.id}, user_id={self.user_id}, title={self.title})>"


class ChatMessage(Base, CreateAtMixin):
    """聊天消息(业务真相源)

    role:
        user      客户
        assistant AI 助手
        agent     人工客服(sender_admin_id/name 记录是谁)
        system    会话事件(转人工/接入/结束), 只在会话内展示, 不进 AI 上下文
    message_type:
        text / plan_card / handoff_notice / system
    client_msg_id: 客户侧幂等键, 重发与重连补拉时去重
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_thread_id_id", "thread_id", "id"),
        UniqueConstraint("thread_id", "client_msg_id", name="uq_chat_messages_client"),
        {"comment": "聊天消息表(业务真相源)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[UUID] = mapped_column(
        DB_UUID(as_uuid=True), nullable=False, comment="所属会话 chat_threads.id"
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="user / assistant / agent / system"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'text'::character varying")
    )
    sender_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="role=agent 时记录客服 admin_users.id"
    )
    sender_admin_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="客服展示名快照(员工改名/删除后仍可渲染)"
    )
    additional_info: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="条款引用/方案卡等结构化附加信息"
    )
    client_msg_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="客户侧幂等键"
    )

    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, thread={self.thread_id}, role={self.role})>"