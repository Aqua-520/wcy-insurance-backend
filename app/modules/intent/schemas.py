"""
投保意向单请求/响应模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IntentCreateRequest(BaseModel):
    """客户提交投保意向"""
    product_id: int
    plan_id: Optional[str] = Field(default=None, max_length=64)
    plan_item_id: Optional[str] = Field(default=None, max_length=64)
    customer_name: str = Field(..., min_length=1, max_length=100)
    customer_phone: str = Field(..., min_length=5, max_length=30)
    remark: str = Field(default="", max_length=1000)


class IntentSummary(BaseModel):
    """意向单摘要"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    intent_no: str
    user_id: Optional[int] = None
    product_id: Optional[int] = None
    customer_name: str
    customer_phone: str
    remark: str
    status: str
    handle_note: str
    # datetime 由 pydantic 自动序列化为 ISO 字符串返回给前端
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IntentListResponse(BaseModel):
    items: list[IntentSummary]
    total: int


class IntentHandleRequest(BaseModel):
    """客服更新跟进状态"""
    status: str = Field(..., pattern="^(contacted|converted|closed)$")
    handle_note: str = Field(default="", max_length=1000)
