"""
存放后端与数据库交互的表数据模型类
基于类对表字段做映射
"""

from uuid import UUID ,uuid4

from sqlalchemy import BigInteger, String, Index
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
    # created_at 和 updated_at 由 Mixin 提供（请确保 Mixin 有定义）

    def __repr__(self) -> str:
        return f"<ChatThread(id={self.id}, user_id={self.user_id}, title={self.title})>"