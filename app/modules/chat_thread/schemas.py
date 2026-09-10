"""
    前后端交互的pydantic请求响应模型
"""
from datetime import datetime
from typing import List, Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, ConfigDict
# 导入引用类型的state中那个状态回显字典类型
from app.agents.schemas import AdditionalInfoData


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
    # model_config = {
    #     'from_attributes': True
    # }

    # 改后
    model_config = ConfigDict(from_attributes=True)

# 前端get响应模型，返回对话详情
class Message(BaseModel):
        """
        封装一问一答聊天详情的对象
        # 通过role区分角色
        """
        role: str  # "user" 或 "assistant"
        content: str
        # 新增条款引用的回显
        additional_info: Optional[AdditionalInfoData] = Field(default=None,description='引用的条款片段回显')

        model_config = ConfigDict(
            json_schema_extra={
                "example": {
                    "role": "user",
                    "content": "我想买保险，预算一年 8000",
                }
            }
        )

class ChatThreadHistoryResponse(BaseModel):
        """
        给前端进行回显的响应对象
        """
        thread_id: UUID  # 使用UUID类型，自动验证格式
        messages: List[Message]  # 消息列表

        # 中断回显字段
        interrupt: Optional[Any] = None  # 没有中断时为 None

        model_config = ConfigDict(
            json_schema_extra={
                "example": {
                    "thread_id": "11111111-1111-1111-1111-111111111111",
                    "messages": [
                        {"role": "user", "content": "我想买保险，预算一年 8000"},
                        {"role": "assistant", "content": "可以，我先给你规划一套组合。"},
                    ],
                }
            }
        )