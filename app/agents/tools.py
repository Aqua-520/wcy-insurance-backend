"""
    此模块为大模型调用的工具模块
"""
import json
from decimal import Decimal
from typing import Literal, Optional, List

from fastapi.encoders import jsonable_encoder
from langchain.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt
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
# 导入rag模块的向量数据库查询对象
from app.rag import question_retriever
# 给langgraph注入自定义信息流
from langgraph.config import get_stream_writer

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
    # 创建保险方案需要人工确认,我们添加一个中断函数
    decision = interrupt(
        # 这里面可以传入任意的中断信息
        # 人工定义一个字典
        {
            # 保险方案pydantic模型,转json
            "plan": insurance_data.model_dump(mode='json'),
            "confirm_info": "小汪提示您,是否确认保存这份方案",
            "action":["approve","reject"]
        }
    )
    # 异常打断函数执行后,再次回到这个函数就没有异常了,开始判断decision里面的值
    if decision.get('action') == 'reject':
        # 用户拒绝保存
        return {
        "message":"保险方案创建失败,用户拒绝保存"
        f"原因:{decision.get('reject_reason')}"
    }

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

# 定义根据知识库查询方案的检索工具
@tool
async def query_product_clause(user_question: str,product_id: int):
    """
    根据用户问题检索指定保险产品的条款内容，用于回答产品细则咨询。
    该工具会从保险条款知识库中检索与用户问题最相关的条款片段，
    并按“章节路径 + 正文”的格式整理返回。适用于解答保险责任、
    免责条款、理赔条件、保障范围等具体条款细节问题。
    :param user_question: 用户问题
    :param product_id: 产品的主键id,你在查寻保险产品列表的时候会得到产品对象,产品id用于限定查询某件产品的条款
    :return: 格式化后的条款片段字符串，多个片段以换行符拼接。
             每个片段格式为：
                 章节:章节路径（用下划线连接）
                 正文内容:条款原文
             若未检索到任何相关内容，则返回空字符串。
    """
    parent_chunks = await question_retriever.retrieve(question=user_question,product_id=product_id)

    if not parent_chunks:
        return "没有找到相关条款"

    # # 定义需要格式化的字符串列表
    # result_chunks = [
    #     f"""
    #         章节:{'_'.join(parent_chunk.section_path)}
    #         正文内容:{parent_chunk.content}
    #     """.strip() # 去掉前后空格
    #     for parent_chunk in parent_chunks
    # ]

    # 修改工具的返回结果为标准的json字符串格式,附带各种详细信息
    """    
    {
        "ref-001": {
            "section_path": "",
            "content": ""
        },
        "ref-002": {
            "section_path": "",
            "content": ""
        }
    }
    """
    result_chunks_dict = {
        f"ref-{index:03d}": {
            "source_id": f"ref-{index:03d}",
            "section_path": parent_chunk.section_path,
            "content": parent_chunk.content,
            "clause_name": parent_chunk.clause_name,
            "product_id": parent_chunk.product_id
        }
        for index,parent_chunk in enumerate(parent_chunks,start=1)
    }

    # 创建自定义事件,将结果额外截出来发给前端
    # 通过调用传参的形式
    writer = get_stream_writer()
    writer({"type": "additional_info", "data": result_chunks_dict})

    # result_chunks每一项存的都是格式化后的字符串结果,我们将列表拼成完整的大字符串返回给大模型作为提示词
    return json.dumps(result_chunks_dict,indent=2,ensure_ascii=False)



