"""
后台管理员账号模型。

与普通用户表完全分离: admin_users.id 与 users.id 会数值碰撞,
登录令牌通过 scope=admin 区分, 不能仅依赖 id 查表。
"""
from typing import Optional

from sqlalchemy import BigInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class AdminUser(Base, CreateAtMixin, UpdateAtMixin):
    """后台管理员"""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'active'::character varying"),
        comment="管理员状态: active / disabled",
    )
    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'admin'::character varying"),
        comment="岗位角色: admin(管理员) / cs(客服) / kb(知识运营)",
    )
