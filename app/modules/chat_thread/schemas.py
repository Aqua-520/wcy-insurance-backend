"""
    前后端交互的pydantic请求响应模型
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# 创建会话的请求模型类
class ChatThreadCreateRequest(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)

    # 自定义数据校验函数,将title字段进行校验,去掉前后空格
    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


# 会话响应模型类
class ChatThreadCreateResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    # 开启字段校验,从数据库模型转到pydantic模型的时候
    # 不开则是将数据库对象转成了json
    # 开了转成pydantic对象,并且进行了安全校验
    model_config = {
        'from_attributes': True
    }