"""
后台管理员数据访问层
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AdminUser


class AdminRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, admin_id: int) -> AdminUser | None:
        return await self.session.scalar(select(AdminUser).where(AdminUser.id == admin_id))

    async def get_by_username(self, username: str) -> AdminUser | None:
        return await self.session.scalar(
            select(AdminUser).where(AdminUser.username == username)
        )
