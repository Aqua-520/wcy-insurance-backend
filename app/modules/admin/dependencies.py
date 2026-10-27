"""
FastAPI 依赖: 解析并校验后台管理员身份。

与普通用户依赖完全隔离:
- 只接受 scope=admin 的令牌;
- 只回查 admin_users 表;
- 旧版无 scope 的用户令牌不会被当作管理员。
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials

# 复用同一个 Bearer 解析器; auto_error=False 以便统一返回业务异常格式
from app.modules.auth.dependencies import bearer_scheme
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.security import decode_access_token
# 独立 session, 避免与请求级 session 的事务状态互相影响
from app.infra.database import AsyncSessionFactory

from .exceptions import AdminInactiveError, AdminTokenInvalidError
from .repository import AdminRepository


@dataclass(frozen=True)
class CurrentAdmin:
    """解析出的当前管理员(可信身份)"""
    admin_id: int
    username: str


async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentAdmin:
    if credentials is None or not credentials.credentials:
        raise AdminTokenInvalidError

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenInvalidError:
        raise AdminTokenInvalidError

    # 必须显式声明管理员域
    if payload.get("scope") != "admin" or payload.get("realm") != "admin":
        raise AdminTokenInvalidError

    try:
        admin_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise AdminTokenInvalidError

    async with AsyncSessionFactory() as session:
        admin = await AdminRepository(session).get_by_id(admin_id)
        if admin is None:
            raise AdminTokenInvalidError
        if admin.status != "active":
            raise AdminInactiveError
        return CurrentAdmin(admin_id=admin.id, username=admin.username)
