"""
此模块来控制前端发来的请求,识别fastapi的接口
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
# 获取数据库会话对象
from app.infra.database import get_session
from .schemas import ProductsResponse,ProductResponse
# 获取业务层类
from .service import ProductService

router = APIRouter(prefix='/api',tags=['保险产品相关路由'])

# 初始化业务层的函数
async def init_product_service(session:AsyncSession = Depends(get_session)):
    # 创建业务层对象
    return ProductService(session=session)

@router.get('/v1/products',response_model=ProductsResponse,summary='首页查询所有默认产品')
async def get_product_List(category: str|None = None,service: ProductService = Depends(init_product_service))-> ProductsResponse:
    """
    调用查询函数拿到返回结果
    :param category: 产品分类名,可为空
    :param service: 依赖注入,拿到业务层的操作对象
    :return: 返回值为一个对象,里面items包的产品数组
    """

    product_result = await service.get_product_list_service(category)

    return ProductsResponse(items=product_result)

# 查询推荐候选产品
@router.get('/v1/products/candidates',response_model=list[ProductResponse],summary='给大模型用,推荐候选产品接口')
async def get_candidate_product_list_router(categories: list[str] = Query(...,description='产品分类，可重复传参'),
                                    premium_min: Decimal | None = Query(None, description="只返回min_premium小于该值的产品"),
                                     limit_per_category: int | None = Query(5, description="每个险种最多返回数量"),
                                     service: ProductService = Depends(init_product_service)):
    """
    根据分类查询推荐候选的商品
    :param categories: 商品的分类,可以传很多种分类
    :param premium_min: 这个价格以内的商品
    :param limit_per_category: 返回几条
    :param service: 业务层操作对象,直接调用增删改查的方法
    :return: list里面包产品对象
    """
    # 路由层直接拿到拼装好的数组返回
    product_result = await service.get_candidate_product_list_service(
        categories=categories,
        premium_min=premium_min,
        limit_per_category=limit_per_category
    )

    return product_result
