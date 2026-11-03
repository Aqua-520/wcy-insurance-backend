"""
后台管理请求/响应模型
"""
from typing import Optional
from datetime import datetime

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


# ---------- 员工账号管理(仅管理员) ----------

class AdminUserItem(BaseModel):
    """员工账号摘要"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str] = None
    role: str
    status: str
    created_at: Optional[datetime] = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int


class AdminUserCreateRequest(BaseModel):
    """新建员工"""
    username: str = Field(..., min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(..., min_length=6, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=100)
    role: str = Field(default="cs", pattern="^(admin|cs|kb)$")


class AdminUserUpdateRequest(BaseModel):
    """编辑员工(不改用户名; 密码留空则不改)"""
    display_name: Optional[str] = Field(default=None, max_length=100)
    role: Optional[str] = Field(default=None, pattern="^(admin|cs|kb)$")
    status: Optional[str] = Field(default=None, pattern="^(active|disabled)$")
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
