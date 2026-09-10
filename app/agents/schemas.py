# 定义一个冻结类,注入到agent对象中,供this这个agent的身上可以携带一些额外的上下文信息
from dataclasses import dataclass
from typing import Literal, Optional, Annotated, Any

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


@dataclass(frozen=True)
# 挂载冻结装饰器,无法再次修改实例属性
class InsuranceAgentContext:
    user_id: int

# 定义智能体意图识别父工作流全局流转的数据模型
# 路由意图常量,限定值只能是这几个
Intent = Literal[
    "chit_chat",
    "recommendation_plan",
    "claim",
    "human_handoff",
    "fallback",
]

# 定义意图识别的大模型节点返回格式,必须遵循此模型
class RouterResultModel(BaseModel):
    # 意图识别的结果
    intent: Intent = Field(...,description='意图识别的结果,必须为限定的类型格式范围')
    reason: str = Field(...,description='意图识别的理由是什么,为什么选这个意图结果')

# 引用信息追加函数
AdditionalInfoData = dict[str,Any] # 自定义类型变量
def merge_additional_info(old: dict[str,AdditionalInfoData],new: dict[str,AdditionalInfoData]):
    # 拼接两个字典
    # 初始化old为空,直接把新的丢到旧的身上完成覆盖即可
    if old is None:
        return new
    # 如果有,直接合并两个字典
    old.update(new)
    return old

class InsuranceAgentState(MessagesState):
    # 继承后自动带一个messages追加形式的列表
    # 新增加两个字段
    previous_workflow: Optional[Intent]
    active_workflow: Optional[Intent]

    # 新增一个字段,保存引用信息
    # 字段的类型是一个字典,字典里面是消息id,消息id后面又跟一个字典
    additional_info: Annotated[dict[str,AdditionalInfoData],merge_additional_info]