"""
此模块来控制前端发来的请求,识别fastapi的接口
"""
from fastapi import APIRouter, Depends

# 获取数据库会话对象
from app.infra.database import get_session
from .schemas import ProductsResponse
# 获取业务层类
from .service import ProductService

router = APIRouter(prefix='/api',tags=['products'])

@router.get('/v1/products',response_model=ProductsResponse)
async def get_product_List(category: str|None = None,session = Depends(get_session)):
    # 创建业务层对象
    service = ProductService(session=session)

    # 调用查询函数拿到返回结果
    product_result = await service.get_product_list(category)

    return ProductsResponse(items=product_result)