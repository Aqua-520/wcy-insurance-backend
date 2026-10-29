"""
    大模型保存保险方案的service业务层
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from .repository import InsurancePlanRepository
from .schemas import InsurancePlanCreate


class InsurancePlanService:
    def __init__(self,session:AsyncSession):
        # 绑定数据库会话
        self.session = session
        # 绑定数据层对象
        self.repository = InsurancePlanRepository(session)


    # 创建保险方案的业务层方法,给大模型的工具函数进行调用使用
    async def create_insurance_plan(self,user_id:int,insurance_data:InsurancePlanCreate) -> dict:
        """保存方案, 返回 plan_id 与各方案项的 id/product_id 列表。

        方案项 id 需要回传给前端, 供产品卡片渲染"去投保"按钮。
        """
        # 开启上下文事务管理器
        async with self.session.begin():
            # 调用数据层方法,将接收到的数据透传给数据层
            orm_plan_obj, orm_item_list = await self.repository.create_insurance_plan(
                user_id=user_id,
                insurance_plan_info=insurance_data
            )
        # 返回保存好的保险plan的id和方案项信息
        return {
            "plan_id": str(orm_plan_obj.id),
            "items": [
                {"item_id": str(item.id), "product_id": item.product_id}
                for item in orm_item_list
            ],
        }