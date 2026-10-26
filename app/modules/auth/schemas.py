"""
认证模块请求/响应模型
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=80, description="登录用户名")
    password: str = Field(..., min_length=6, max_length=128, description="登录密码")
    email: EmailStr = Field(..., description="邮箱")
    display_name: Optional[str] = Field(default=None, max_length=100, description="展示昵称")


class LoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., min_length=1, description="用户名或邮箱")
    password: str = Field(..., min_length=1, description="登录密码")


class UserSummary(BaseModel):
    """返回给前端的用户摘要(不含密码)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    display_name: Optional[str] = None
    status: str


class TokenResponse(BaseModel):
    """登录/注册成功后返回的令牌与用户信息"""
    access_token: str
    token_type: str = "bearer"
    user: UserSummary
