"""
员工账号管理业务层(仅管理员可调用)。

规则:
- 用户名不可改、不可重复; 密码 bcrypt 加盐哈希(与登录同套 security);
- 不能禁用/降级/删除自己;
- 必须至少保留一名 active 管理员(禁用/降级/删除前校验)。
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security import hash_password

from .exceptions import (
    AdminUserConflictError,
    AdminUserExistsError,
    AdminUserNotFoundError,
)
from .models import AdminUser
from .repository import AdminRepository


class AdminUserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = AdminRepository(session)

    async def list_users(self) -> list[AdminUser]:
        return await self.repository.list_all()

    async def _get_or_404(self, user_id: int) -> AdminUser:
        admin = await self.repository.get_by_id(user_id)
        if admin is None:
            raise AdminUserNotFoundError
        return admin

    async def _active_admin_count(self, exclude_id: int | None = None) -> int:
        query = select(func.count()).select_from(AdminUser).where(
            AdminUser.role == "admin",
            AdminUser.status == "active",
        )
        if exclude_id is not None:
            query = query.where(AdminUser.id != exclude_id)
        return int((await self.session.execute(query)).scalar_one())

    async def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None,
        role: str,
    ) -> AdminUser:
        if await self.repository.get_by_username(username) is not None:
            raise AdminUserExistsError
        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
            status="active",
        )
        self.session.add(admin)
        await self.session.commit()
        await self.session.refresh(admin)
        return admin

    async def update_user(
        self,
        user_id: int,
        operator_id: int,
        display_name: str | None,
        role: str | None,
        status: str | None,
        password: str | None,
    ) -> AdminUser:
        admin = await self._get_or_404(user_id)
        # 不能动自己(禁用/降级会让操作者当场失去权限)
        if user_id == operator_id and (role not in (None, "admin") or status == "disabled"):
            raise AdminUserConflictError("不能修改自己的岗位或禁用自己")
        # 管理员岗位是唯一全能角色, 必须保住至少一名 active 管理员
        loses_admin = (admin.role == "admin" and admin.status == "active") and (
            (role not in (None, "admin")) or status == "disabled"
        )
        if loses_admin and await self._active_admin_count(exclude_id=user_id) == 0:
            raise AdminUserConflictError("至少保留一名启用状态的管理员")
        if display_name is not None:
            admin.display_name = display_name
        if role is not None:
            admin.role = role
        if status is not None:
            admin.status = status
        if password:
            admin.password_hash = hash_password(password)
        await self.session.commit()
        await self.session.refresh(admin)
        return admin

    async def delete_user(self, user_id: int, operator_id: int) -> None:
        admin = await self._get_or_404(user_id)
        if user_id == operator_id:
            raise AdminUserConflictError("不能删除自己")
        if admin.role == "admin" and admin.status == "active":
            if await self._active_admin_count(exclude_id=user_id) == 0:
                raise AdminUserConflictError("至少保留一名启用状态的管理员")
        await self.session.delete(admin)
        await self.session.commit()
