# 调用repository类,拿到对象,然后调用各种数据库增删改查的模块
#  此模块属于业务层,由上层api路由创建实例对象调用方法
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Product
# 导入下一层的类,创建数据库操作对象
from .repository import ProductRepository


class ProductService:
    def __init__(self,session:AsyncSession):
        # 这里需要将session引擎拿到,传给repository下一层的类创建数据库操作对象
        self.session = session
        # 拿到数据库操作实例对象
        self.repository = ProductRepository(session)

    # 调用查询产品的方法
    async def get_product_list_service(self,category:str | None)-> list[Product]:
        # 这里数据库函数调用为异步,需要加await拿到返回结果
        return await self.repository.get_product_list_repository(category)

    # 查询
    async def get_candidate_product_list_service(self,categories: list[str],
                                         premium_min: Decimal|None,
                                         limit_per_category:int|None=5):
        # 循环调用种类,拼接结果数组返回
        result_list:list[Product] = []

        for category in categories:
            # 查询数据库
            # 使用extend接收一个可迭代对象,会自动遍历将里面的东西塞入新容器
            result_list.extend(await self.repository.
                               get_candidate_product_list_repository(category,premium_min,limit_per_category))

        # 返回结果是拼装好的数组,直接返回路由层
        return result_list