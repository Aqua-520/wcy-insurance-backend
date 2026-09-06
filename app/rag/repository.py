# 导入数据模型
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ParentChunk

# 创建父块的数据库操作类
class ParentChunkRepository:
    def __init__(self,session: AsyncSession):
        self.session = session

    # 批量删除的方法
    async def delete_parent_chunks(self,product_id: int) -> None:
        """
        删除同一个保险产品的所有文档切片
        :param product_id: 保险产品id
        :return: 无返回
        """
        await self.session.execute(
            delete(
                ParentChunk
            ).where(ParentChunk.product_id == product_id)
        )

    async def add_parent_chunks(self,parent_chunks: list[ParentChunk]) -> None:
        """
        先做删除,然后添加到数据库
        :param parent_chunks: 父亲的chunk
        :return: 无返回值
        """
        self.session.add_all(parent_chunks)

    # 根据子块保存的所属父块id,查询到父块的内容
    async def find_by_parent_id(self,parent_ids: list[str]) -> list[ParentChunk]:
        """
        子块通过语义匹配,检索到数据库内容,拿到里面存储的父块id,来查询父块的详情
        :param parent_ids: 父块的主键
        :return: 数据库查询结果列表对象
        """
        result = await self.session.scalars(
            # 一次性查询多个 ID 对应的记录，避免循环单条查询,in_ 包含这个列表里面存储的所有id,进行匹配全部返回
            select(ParentChunk).where(ParentChunk.id.in_(parent_ids))
        )
        # 直接返回
        return list(result.all())