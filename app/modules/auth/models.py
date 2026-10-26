"""
用户表 ORM 模型(映射已有的 users 表)
"""
from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class User(Base, CreateAtMixin, UpdateAtMixin):
    """保险商城用户账户"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, comment="登录用户名")
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, comment="邮箱")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 密码哈希")
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="展示昵称")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="active", comment="账号状态: active/disabled"
    )
