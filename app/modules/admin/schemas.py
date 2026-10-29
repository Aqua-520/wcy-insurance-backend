"""
后台管理请求/响应模型
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminLoginRequest(BaseModel):
    """管理员登录请求"""
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=128)


class AdminSummary(BaseModel):
    """返回给前端的管理员摘要(不含密码)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str] = None
    status: str
    role: str = "admin"


class AdminTokenResponse(BaseModel):
    """管理员登录成功响应"""
    access_token: str
    token_type: str = "bearer"
    admin: AdminSummary
