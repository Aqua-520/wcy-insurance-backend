"""
    用户从前端窗口send发送消息时的请求响应模型定义
"""
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequestModel(BaseModel):
    thread_id: UUID
    message: Optional[str] = Field(default=None,description='用户本轮发送的消息')
    # 请求模型携带可选参数
    # 定义成字典,也就是我们工具中断函数传入的数据格式
    decision: Optional[dict[str,Any]] = Field(default=None,description='用户决策字典')