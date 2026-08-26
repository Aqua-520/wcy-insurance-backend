from uuid import UUID

from sqlalchemy import select, and_

from .models import ChatThread
# 创建表操作类
class ChatThreadRepository:
    # 初始化拿到数据库会话对象
    def __init__(self,session):
        # 给实例对象身上绑定数据库会话对象
        self.session = session


    async def add(self,new_chat_thread: ChatThread):
        """
        新建会话的操作
        :param: 传来的消息对象,直接新增到数据库中
        :return: 无
        """
        # 将业务层新建的表对象直接丢入数据库会话对象进行存储
        self.session.add(new_chat_thread)

    async def get_chat_thread_list_repository(self,user_id: int)->list[ChatThread]:
        """
        显示会话消息列表
        :param user_id: 用户登录身份识别,只显示同一个用户的
        :return: 返回查询结果列表
        """
        # 查询结果
        result = await self.session.scalars(
            select(ChatThread).where(ChatThread.user_id == user_id).order_by(ChatThread.updated_at.desc(),
                                                                             ChatThread.created_at.desc())
        )
        # 返回是一组表对象
        return list(result.all())

    async def get_chat_thread_owner_repository(self,thread_id: UUID, user_id: int)-> ChatThread:
        """
        查询单条数据对象的方法
        :param thread_id: uuid,主键,也就是当前会话的唯一标识
        :param user_id: 当前登录用户
        :return: 查询出来的表对象
        """
        return await self.session.scalar(
            select(ChatThread).where(and_(ChatThread.id == thread_id,ChatThread.user_id == user_id))
        )

    async def delete_chat_thread_owner_repository(self,chat_thread)-> None:
        """
        此方法拿到表对象,将表对象丢入delete方法中删除
        :param chat_thread:
        :return: 无
        """
        # 直接删除即可,返回值无
        await self.session.delete(chat_thread)