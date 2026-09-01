"""
    此模块为大模型调用的工具模块
"""
from decimal import Decimal
from typing import Literal, Optional, List

from fastapi.encoders import jsonable_encoder
from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

# 导入sqlalchemy数据库会话对象
from app.infra.database import AsyncSessionFactory
from app.modules.product.models import Product
# 导入产品查询业务模块的类
from app.modules.product.service import ProductService
# 导入保险方案生成的规定数据类
from app.modules.insurance_plan.schemas import InsurancePlanCreate
# 导入保险方案业务层类
from app.modules.insurance_plan.service import InsurancePlanService
# 导入当前agent被指定的上下文对象类型
from .schemas import InsuranceAgentContext


# 定义保费推荐工具的pydantic模型,做数据校验,并且写上描述让大模型精准判断
class QueryCandidateProductsToolResult(BaseModel):
    """
        用于大模型传输的保险产品结构
        允许从数据库orm对象转成pydantic数据校验模型
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(...,description="产品ID（内部主键）")
    name: str = Field(...,description="商城展示名称")
    clause_name: str = Field(...,description="主条款文件名，包含 .pdf 后缀")
    category: str = Field(...,description="险种分类：医疗、重疾、意外或寿险")
    insurer: str = Field(...,description="承保保险公司")
    image_url: Optional[str] = Field(default=None, description="产品展示图片地址")
    description: Optional[str] = Field(default=None, description="产品简介")
    min_premium: Optional[Decimal] = Field(default=None, description="产品公开的最低年缴保费参考")
    max_premium: Optional[Decimal] = Field(default=None, description="产品公开的最高保费参考，可为空")
    target_group: Optional[str] = Field(default=None, description="适用人群说明")
    highlights: Optional[List[str]] = Field(default=None, description="产品亮点列表")


# 定义保费和险种进行产品推荐的工具,免得大模型瞎几把回答用户消息
@tool
async def query_candidate_products(
    # 哪几类商品
    categories: list[Literal["medical", "critical_illness", "life", "accident"]],
    # 检索低于多少钱的商品
    premium_min: Decimal | None = None,
    # 检索不超过多少条产品
    limit_per_category: int = 5
):
    """
    根据险种和保费条件查询可用于推荐的候选保险产品。当用户咨询具体保险产品或需要保险产品推荐时使用。
    :param categories: 产品分类列表，可选值为 medical（医疗险）、critical_illness（重疾险）、life（寿险）、accident（意外险）。
    :param premium_min: 最低保费上限，可选参数，只返回最低保费小于该值的产品。
    :param limit_per_category: 每个险种最多返回的产品数量，可选参数，默认5。
    :return:
    """
    # 通过会话工厂新生成一个session,跟业务层fastapi接口形成解耦,相当于开小灶
    async with AsyncSessionFactory() as session:
        # 生成product服务层对象
        product_service = ProductService(session)

        # 通过服务对象进行数据库查询操作
        # 此操作查询出来的是sqlalchemy对象,需要转成pydantic对象,发送给langchain框架做操作
        product_result:list[Product] = await product_service.get_candidate_product_list_service(
            categories=categories,
            premium_min=premium_min,
            limit_per_category=limit_per_category
        )
        # 将列表中的orm转成pydantic对象
        pydantic_product_result = [QueryCandidateProductsToolResult.model_validate(i) for i in product_result]

        return jsonable_encoder(pydantic_product_result)

# 定义保存保险方案的工具函数
# 大模型按规则组织好数据,作为参数传到工具函数中,由工具函数调用insurance_plan中的业务层代码实现传递数据
@tool
async def create_insurance_plan(insurance_data:InsurancePlanCreate,runtime:ToolRuntime[InsuranceAgentContext]) -> dict[str,str]:
    """
    工具函数通过agent身上的上下文属性runtime,注入用户id,langchain会在模型准备调用工具的时候自动注入参数
    :param insurance_data: 保险方案的数据格式
    :return: 保险方案生成的结果
    """
    # 没有路由层注入session,我们自己用工厂再开一个session
    async with AsyncSessionFactory() as session:
        # 获取到保险产品业务层的对象
        insurance_plan_service = InsurancePlanService(session)

        # 调用创建保险方案的方法,拿到返回的方案id
        plan_id = await insurance_plan_service.create_insurance_plan(
            user_id=runtime.context.user_id,
            insurance_data=insurance_data
        )

    # 告诉大模型调用成功的消息
    return {
        "message":"保险方案创建成功",
        # plan_id是uuid格式,需要转换成字符串
        "plan_id":str(plan_id)
    }





