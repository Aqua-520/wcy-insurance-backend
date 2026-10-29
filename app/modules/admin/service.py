"""
后台管理员认证业务层
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security import create_access_token, verify_password

from .exceptions import AdminInactiveError, InvalidAdminCredentialsError
from .models import AdminUser
from .repository import AdminRepository
from .schemas import AdminLoginRequest


class AdminAuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = AdminRepository(session)

    async def login(self, data: AdminLoginRequest) -> AdminUser:
        admin = await self.repository.get_by_username(data.username)
        # 统一错误提示, 避免管理员账号被枚举
        if admin is None:
            raise InvalidAdminCredentialsError

        # bcrypt 是同步 CPU 操作, 放进线程避免阻塞事件循环
        valid = await asyncio.to_thread(verify_password, data.password, admin.password_hash)
        if not valid:
            raise InvalidAdminCredentialsError
        if admin.status != "active":
            raise AdminInactiveError
        return admin

    @staticmethod
    def issue_token(admin: AdminUser) -> str:
        """签发管理员令牌, scope=admin 与普通用户令牌隔离"""
        return create_access_token(
            admin.id,
            extra={
                "username": admin.username,
                "scope": "admin",
                "realm": "admin",
                "role": admin.role,
            },
        )
