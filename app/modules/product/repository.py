# 此模块负责直接对接数据库,进行crud的操作
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, ColumnElement, and_
from .models import Product

class ProductRepository:
    # 封装数据库的数据查询,将数据返回给上一层:服务层进行操作
    def __init__(self,session: AsyncSession):
        # 将数据库连接引擎传入,进行操作
        self.session = session

    # 查询产品列表
    async def get_product_list(self,category: str | None)-> list[Product]:
        """
        从数据库中查询产品列表,并返回数据
        :param category: 可有可无,保险产品的类型
        :return: 保险产品查询结果数组
        """
        # 看看是否有查询参数
        # 定义查询条件list
        sql_query: list[ColumnElement[bool]] = [Product.status == 'active']
        # 看看需不需要按分类查询
        if category is not None:
            sql_query.append(Product.category == category) # type: ignore

        result = await self.session.scalars(
            # id升序排序
            select(Product).where(and_(*sql_query)).order_by(Product.id.asc())
        )
        # 返回
        return list(result.all())
