"""
工单请求/响应模型
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TicketSummary(BaseModel):
    """工单摘要(客户与客服共用)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_no: str
    ticket_type: str
    status: str
    summary: str
    assigned_admin_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TicketMessageItem(BaseModel):
    """一条沟通记录"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender_role: str
    content: str
    created_at: Optional[str] = None


class TicketDetail(TicketSummary):
    """工单详情(含沟通记录)"""
    messages: list[TicketMessageItem] = []


class TicketListResponse(BaseModel):
    items: list[TicketSummary]
    total: int


class CreateTicketRequest(BaseModel):
    """客户主动发起工单(投诉/理赔咨询等)"""
    ticket_type: str = Field(..., pattern="^(complaint|claim|handoff)$")
    summary: str = Field(..., min_length=2, max_length=2000)


class CustomerMessageRequest(BaseModel):
    """客户补充说明"""
    content: str = Field(..., min_length=1, max_length=2000)


class StaffReplyRequest(BaseModel):
    """客服回复"""
    content: str = Field(..., min_length=1, max_length=2000)


class StaffUpdateStatusRequest(BaseModel):
    """客服变更工单状态(领取/关闭)"""
    action: str = Field(..., pattern="^(claim|close)$")
