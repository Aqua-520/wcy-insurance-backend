"""
    负责和数据库交互
    我们需要操作两张表
"""
from sqlalchemy.ext.asyncio import AsyncSession
# 导入方案创建类
from .schemas import InsurancePlanCreate
# 导入数据库orm模型
from .models import InsurancePlan, InsurancePlanItem
from decimal import Decimal


class InsurancePlanRepository:
    def __init__(self,session:AsyncSession):
        # 将会话id绑到对象实例身上
        self.session = session

    # 创建保险方案的方法
    async def create_insurance_plan(self,user_id:int,insurance_plan_info:InsurancePlanCreate) -> InsurancePlan:
        """
        我们需要将业务层传入的pydantic类型的数据对象转换成orm对象
        进行数据库写入操作
        业务层传入保险方案的对象,里面的items是单条推荐保险产品的对象
        从保险方案对象中再拆出items列表,把里面的产品对象拆出来改造成子表的orm对象,进行数据库写入操作即可
        :param user_id: 用户唯一标识id
        :param insurance_plan_info: 大模型构建的pydantic保险对象
        :return: 返回值是数据库orm保险方案对象
        """
        # 摘出保险产品列表
        product_list = insurance_plan_info.items
        # 计算保费总额
        annual_premium_budget_result = sum([item.annual_premium_budget for item in product_list
                                            if item.annual_premium_budget is not None],Decimal(0))

        # 创建数据库保险方案表对象
        orm_insurance_plan = InsurancePlan(
            # 里面有些字段是自动生成的,比如id和create_time
            user_id=user_id,
            # 大模型传入的必填参数
            plan_name=insurance_plan_info.plan_name,
            summary=insurance_plan_info.summary,
            insured_profile=insurance_plan_info.insured_profile,
            # 手动计算的价格参数
            annual_premium_budget=annual_premium_budget_result,
            # 方案投保状态默认为未投保,模型定义也没传入,先不管
        )
        # 写入数据库
        self.session.add(orm_insurance_plan)

        # 将保险plan直接刷到数据库,避免保险产品的外键绑定主键失败
        await self.session.flush()

        # 创建保险orm对象列表
        orm_product_list = [
            InsurancePlanItem(
                plan_id=orm_insurance_plan.id,
                product_id=item.product_id,
                priority=item.priority,
                recommendation_reason=item.recommendation_reason,
                annual_premium_budget=item.annual_premium_budget,

            )
            for item in product_list
        ]
        # 将列表添加进数据库
        self.session.add_all(orm_product_list)

        # 返回转换完毕的plan表对象
        return orm_insurance_plan