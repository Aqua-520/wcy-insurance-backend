"""
问答反馈请求/响应模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreateRequest(BaseModel):
    """客户提交反馈"""
    thread_id: Optional[str] = Field(default=None, max_length=64)
    question: str = Field(default="", max_length=5000)
    answer: str = Field(default="", max_length=20000)
    rating: str = Field(..., pattern="^(up|down)$")
    reason: str = Field(default="", max_length=1000)


class FeedbackSummary(BaseModel):
    """反馈摘要(客户与后台共用)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: Optional[str] = None
    question: str
    answer: str
    rating: str
    reason: str
    category: Optional[str] = None
    status: str
    handle_note: str
    customer_confirm: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackSummary]
    total: int


class FeedbackHandleRequest(BaseModel):
    """后台归因与处理"""
    category: str = Field(..., pattern="^(retrieval|clause|model|other)$")
    status: str = Field(..., pattern="^(improving|resolved|rejected)$")
    handle_note: str = Field(default="", max_length=2000)


class FeedbackConfirmRequest(BaseModel):
    """客户确认改进结果"""
    confirm: str = Field(..., pattern="^(accepted|rejected)$")
