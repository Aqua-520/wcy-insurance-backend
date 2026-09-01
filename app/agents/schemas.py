# 定义一个冻结类,注入到agent对象中,供this这个agent的身上可以携带一些额外的上下文信息
from dataclasses import dataclass


@dataclass(frozen=True)
# 挂载冻结装饰器,无法再次修改实例属性
class InsuranceAgentContext:
    user_id: int