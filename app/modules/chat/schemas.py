"""
    用户从前端窗口send发送消息时的请求响应模型定义
"""
from uuid import UUID

from pydantic import BaseModel


class ChatRequestModel(BaseModel):
    thread_id: UUID
    message: str