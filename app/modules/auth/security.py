"""
安全工具: 密码哈希(bcrypt) 与 JWT 令牌的签发/解析
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from .exceptions import TokenInvalidError


def hash_password(plain_password: str) -> str:
    """对明文密码做 bcrypt 加盐哈希"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码与库内哈希是否匹配; 哈希格式非法时直接返回 False"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, extra: dict[str, Any] | None = None) -> str:
    """为指定用户签发 access_token(JWT)"""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),       # 主体: 用户 id(字符串)
        "iat": now,                # 签发时间
        "exp": now + timedelta(minutes=settings.auth.access_token_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.auth.secret_key, algorithm=settings.auth.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并校验 JWT, 失败抛 TokenInvalidError"""
    try:
        return jwt.decode(token, settings.auth.secret_key, algorithms=[settings.auth.algorithm])
    except jwt.PyJWTError:
        raise TokenInvalidError
