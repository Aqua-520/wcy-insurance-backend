"""人工接管: 前后端交互模型。"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.schemas import AdditionalInfoData


class HandoffResponse(BaseModel):
    """转人工申请/取消的结果(客户侧展示排队信息)。"""

    thread_id: UUID
    mode: str
    # 排队位次(1 = 下一个就轮到你), 已在人工服务中时为 0
    queue_position: int = 0
    # 预计等待秒数(按排队人数估算, 前端文案必须是"预计")
    est_wait_seconds: int = 0
    notice: str = ""
    claimed_by_name: Optional[str] = None
    # 此刻没有客服在线: 只告知, 不排队也不留单
    offline: bool = False


class ChatMessageItem(BaseModel):
    id: int
    role: str
    content: str
    message_type: str = "text"
    sender_admin_name: Optional[str] = None
    additional_info: Optional[AdditionalInfoData] = None
    created_at: Optional[datetime] = None


class ChatMessagesIncrementalResponse(BaseModel):
    """增量拉取: after_id 之后的新消息(正文真相源)。"""

    thread_id: UUID
    mode: str
    items: list[ChatMessageItem]
    # 下次请求传这个值; 无新消息时与请求的 after_id 相同
    last_id: int = 0
    has_more: bool = False


class AgentSessionItem(BaseModel):
    """客服工作台的会话卡片。"""

    thread_id: str
    user_id: int
    customer_name: str
    title: str
    mode: str
    waiting_seconds: int = 0
    claimed_by: Optional[int] = None
    claimed_by_name: Optional[str] = None
    last_message: str = ""
    last_message_role: str = ""
    last_message_at: Optional[datetime] = None
    unread: int = 0


class AgentSessionListResponse(BaseModel):
    items: list[AgentSessionItem]
    total: int
    # 当前在排队等待接入的数量(工作台红点用)
    waiting: int = 0
    mine: int = 0
    # 在线客服数(90 秒内有后台请求); 0 表示此刻没人能接, 客户转人工会直接留言
    online: int = 0


class AgentMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class EndSessionRequest(BaseModel):
    # 交接说明: AI 恢复回答时读这一句, 所以必填
    handoff_note: str = Field(..., min_length=1, max_length=500)


class EndSessionResponse(BaseModel):
    thread_id: UUID
    mode: str
    handoff_note: str
    ai_resume_injected: bool = False
    detail: str = ""
