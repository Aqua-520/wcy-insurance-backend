"""
用户数据访问层
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.id == user_id))

    async def get_by_username(self, username: str) -> User | None:
        """登录支持用户名或邮箱, 这里按用户名查(邮箱在 service 兜底)"""
        return await self.session.scalar(select(User).where(User.username == username))

    async def get_by_login(self, login: str) -> User | None:
        """按用户名或邮箱查找账号"""
        return await self.session.scalar(
            select(User).where((User.username == login) | (User.email == login))
        )

    async def exists_by_username_or_email(self, username: str, email: str) -> bool:
        user = await self.session.scalar(
            select(User.id).where((User.username == username) | (User.email == email))
        )
        return user is not None

    def add(self, user: User) -> None:
        self.session.add(user)
