# 此模块负责直接对接数据库,进行crud的操作
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from sqlalchemy import select, ColumnElement, and_
from .models import Product

class ProductRepository:
    # 封装数据库的数据查询,将数据返回给上一层:服务层进行操作
    def __init__(self,session: AsyncSession):
        # 将数据库连接引擎传入,进行操作
        self.session = session

    # 查询产品列表
    async def get_product_list_repository(self,category: str | None)-> list[Product]:
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

    # 查询推荐候选产品
    async def get_candidate_product_list_repository(self,category: str,
                                         premium_min: Decimal | None,
                                         limit_per_category: int | None = 5
                                         )-> list[Product]:
        """
        从数据库根据指定查询条件进行筛选查询
        :param category: 产品分类
        :param premium_min: 只返回 min_premium < premium_min 的产品
        :param limit_per_category: 每次最大返回数量,分页
        :return: 保险产品查询结果数组
        """
        # 服务层通过循环进行多种类查询,不要让数据库一次查询多种种类
        conditions = [
            Product.status == 'active',
            Product.category == category
        ]

        # 看看有没有传入premium_min这个参数
        if premium_min is not None:
            conditions.append(Product.min_premium < premium_min)

        # 进行数据库查询
        result = await self.session.scalars(
            # 根据id升序,并且将字段为null的排到末尾
            select(Product).where(and_(*conditions)).order_by(Product.id.asc())
            .limit(limit_per_category)
        )

        # 返回查询结果
        return list(result.all())
