# 调用repository类,拿到对象,然后调用各种数据库增删改查的模块
#  此模块属于业务层,由上层api路由创建实例对象调用方法
from sqlalchemy.ext.asyncio import AsyncSession
# 导入下一层的类,创建数据库操作对象
from .repository import ProductRepository


class ProductService:
    def __init__(self,session:AsyncSession):
        # 这里需要将session引擎拿到,传给repository下一层的类创建数据库操作对象
        self.session = session
        # 拿到数据库操作实例对象
        self.repository = ProductRepository(session)

    # 调用查询产品的方法
    async def get_product_list(self,category:str | None):
        # 这里数据库函数调用为异步,需要加await拿到返回结果
        return await self.repository.get_product_list(category)