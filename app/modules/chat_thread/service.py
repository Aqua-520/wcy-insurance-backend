"""
    会话业务层
"""
from uuid import UUID

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from .repository import ChatThreadRepository
from .models import ChatThread
# 导入自定义异常
from .exceptions import ChatThreadNotFoundError
from .schemas import ChatThreadHistoryResponse, Message


class ChatThreadService:
    # 构造函数
    def __init__(self,session:AsyncSession,agent:CompiledStateGraph):
        # 将数据库会话对象保存到当前实例身上,并且将数据库层对象保存到对象身上
        self.session = session
        # 拿到数据层操作对象
        self.repository = ChatThreadRepository(session)
        # 对象身上新绑定一个agent对象
        self.agent = agent

    # 新增会话的方法
    async def add(self,user_id:int, title: str)-> ChatThread:
        """
        创建数据库表对象,并且调用数据层方法传入
        :param user_id:
        :param title:
        :return: 返回完整的表对象
        """

        # 上一层拿到用户id,和title,主键id创建对象自动创建,并且自动生成建表时间和修改时间
        chat_thread = ChatThread(user_id=user_id,title=title)

        # 开启数据库事务
        async with self.session.begin():
            # 操作数据库的方法通通属于异步
            await self.repository.add(chat_thread)

        # return卸载事务结束之后
        # 这里表对象自动包含建表语句所有信息,直接丢回去即可
        return chat_thread

    # 查询会话消息列表
    async def get_chat_thread_list_service(self,user_id)-> list[ChatThread]:
        """
        调用数据层,查询数据列表直接返回
        :param user_id:
        :return: 一组表对象
        """
        result = await self.repository.get_chat_thread_list_repository(user_id)

        return result

    # 修改会话信息标题
    async def update_chat_thread_service(self,thread_id:UUID ,user_id:int ,title:str)-> ChatThread:
        """
        拿到数据层对象,对数据库对象进行操作
        :param user_id: 当前登录用户
        :param title: 需要更新的标题
        :param thread_id: 聊天会话唯一标识
        :return:
        """
        # 开启事务,对字段进行操作
        async with self.session.begin():
            # 调用数据层拿到查询对象
            chat_thread = await self.repository.get_chat_thread_owner_repository(thread_id=thread_id,
                                                                                 user_id=user_id, )
            # 判断有没有查询到数据
            if chat_thread is None:
                # 如果没有查到则抛出异常
                raise ChatThreadNotFoundError

            chat_thread.title = title

            # 刷新
            await self.session.flush()
            # 刷新表对象
            await self.session.refresh(chat_thread)

        # 返回更新后的表对象
        return chat_thread

    # 删除会话信息
    async def delete_chat_thread_owner_service(self,thread_id:UUID, user_id:int)-> None:
        """
        接收两个参数,需要删除的会话id和用户标识id
        :param thread_id: 会话id
        :param user_id: 用户唯一标识
        :return: 不需要返回值
        """
        async with self.session.begin():
            # 开启事务
            # 先进行查询
            chat_thread = await self.repository.get_chat_thread_owner_repository(thread_id, user_id)

            # 判断是否存在
            if chat_thread is None:
                # 如果为空则抛出异常
                raise ChatThreadNotFoundError

            # 通过非空判断执行删除操作
            # 先删除同会话id的会话详情历史
            # 从agent对象身上直接能拿到checkpointer检查点对象,通过这个对象执行数据库删除操作
            await self.agent.checkpointer.adelete_thread(str(thread_id))

            # 再删除会话id
            await self.repository.delete_chat_thread_owner_repository(chat_thread)

        # 数据库操作完毕,不需要返回值

    # 回显会话详情历史
    async def get_chat_content_service(self,user_id: int,thread_id:UUID) -> ChatThreadHistoryResponse:
        """
        接收用户id,和会话id,通过agent对象,langchain自动查找数据库快照
        解析成前端要求的响应格式进行返回
        :param user_id: 用户唯一标识
        :param thread_id: 会话id
        :return: 返回符合规范的响应格式对象
        """
        # 先根据user_id查一把，看看有没有会话消息管理的对象
        chat_thread = await self.repository.get_chat_thread_owner_repository(thread_id, user_id)

        # 判断是否存在
        if chat_thread is None:
            # 如果为空则抛出异常
            raise ChatThreadNotFoundError

        # 构建会话config，会话id
        # 前端传入会话id
        _config = RunnableConfig(configurable={"thread_id": str(thread_id)})

        # 通过agent对象，拿到消息快照
        snapshot = await self.agent.aget_state(_config)

        # 定义消息数组
        message_list:list[Message] = []
        # 循环消息快照,将快照映射成我们需要返回的数据格式
        for item in snapshot.values.get('messages', []):
            if isinstance(item, HumanMessage):
                # 如果是用户消息,则构建消息对象,设置角色为user
                user_obj = Message(role='user',content=item.text)
                message_list.append(user_obj)
            elif isinstance(item, AIMessage):
                assistant_obj = Message(role='assistant',content=item.text)
                message_list.append(assistant_obj)
            else:
                # 忽略工具调用消息
                continue

        # 赋值完成后,返回最后的响应体对象
        return ChatThreadHistoryResponse(thread_id=thread_id,messages=message_list)