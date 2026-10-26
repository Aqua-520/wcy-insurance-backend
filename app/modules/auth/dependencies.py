"""
FastAPI 依赖: 从 Authorization 头解析当前登录用户
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# 鉴权查库使用独立 session, 不与业务 service 共享请求级 session:
# FastAPI 会对同一依赖(get_session)做缓存, 若共用, 这里的 SELECT 会触发
# autobegin, 导致业务层再调 session.begin() 时报 "transaction already begun"
from app.infra.database import AsyncSessionFactory

from .exceptions import TokenInvalidError, UserInactiveError
from .repository import UserRepository
from .security import decode_access_token

# auto_error=False: 缺失令牌时不抛 FastAPI 默认异常, 统一走我们的业务异常格式
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """解析出的当前登录用户(可信身份)"""
    user_id: int
    username: str


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    # 1.必须携带 Bearer 令牌
    if credentials is None or not credentials.credentials:
        raise TokenInvalidError

    # 2.验签并解析令牌
    payload = decode_access_token(credentials.credentials)
    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise TokenInvalidError

    # 3.回查数据库, 确认用户仍然存在且未被停用(用独立 session, 随查随关)
    async with AsyncSessionFactory() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None:
            raise TokenInvalidError
        if user.status != "active":
            raise UserInactiveError

        return CurrentUser(user_id=user.id, username=user.username)
