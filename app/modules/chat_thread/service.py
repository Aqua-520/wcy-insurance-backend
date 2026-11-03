"""
    会话业务层
"""
from uuid import UUID

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.admin.models import AdminUser
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

        # 人工接管改造: 业务消息表有数据就以库为准
        # (checkpointer 只服务 AI 推理; 前端渲染要能看到客服消息与会话事件)
        if await self.repository.count_messages(thread_id) > 0:
            return await self._history_from_db(chat_thread)

        # 构建会话config，会话id
        # 前端传入会话id
        _config = RunnableConfig(configurable={"thread_id": str(thread_id)})

        # 通过agent对象，拿到消息快照
        snapshot = await self.agent.aget_state(_config)

        # 如果有条款引用,将快照中的条款引用一起发给前端
        additional_info = snapshot.values.get('additional_info',{})

        # 定义消息数组
        message_list:list[Message] = []
        # 循环消息快照,将快照映射成我们需要返回的数据格式
        for item in snapshot.values.get('messages', []):
            if isinstance(item, HumanMessage):
                # 如果是用户消息,则构建消息对象,设置角色为user
                user_obj = Message(role='user',content=item.text,additional_info=additional_info.get(item.id))
                message_list.append(user_obj)
            elif isinstance(item, AIMessage):
                assistant_obj = Message(role='assistant',content=item.text,additional_info=additional_info.get(item.id))
                message_list.append(assistant_obj)
            else:
                # 忽略工具调用消息
                continue

        """
            处理中断信息
            如果上次用户没处理,则需要做中断信息回显继续操作
        """
        interrupts = None
        if hasattr(snapshot,'interrupts') and snapshot.interrupts:
            # 先看新版字段有没有
            interrupts = snapshot.interrupts
        elif hasattr(snapshot, 'tasks') and snapshot.tasks:
            # 再看看旧版tasks属性里面找
            # 找到了则循环取值
            for task in snapshot.tasks:
                if hasattr(task,'interrupts') and task.interrupts:
                    interrupts = task.interrupts
                    # 找到了就结束循环
                    break

        # 赋值完成后,返回最后的响应体对象
        return ChatThreadHistoryResponse(thread_id=thread_id,messages=message_list,
                                         interrupt=interrupts[0].value if interrupts else None,
                                         mode=(getattr(chat_thread, "mode", None) or "ai"),
                                         handoff_note=(getattr(chat_thread, "handoff_note", None) or None),
                                         )

    async def _history_from_db(self, chat_thread: ChatThread) -> ChatThreadHistoryResponse:
        """从业务消息表回显历史(含客服消息与会话事件)。

        老会话(升级前)没有 chat_messages 行, 走上面的 checkpointer 分支, 无需迁移。
        """
        thread_id = chat_thread.id
        rows = await self.repository.list_messages(thread_id, after_id=0, limit=500)
        message_list = [
            Message(
                id=row.id,
                role=row.role,
                content=row.content or "",
                message_type=row.message_type or "text",
                sender_admin_name=row.sender_admin_name,
                additional_info=row.additional_info,
                created_at=row.created_at,
            )
            for row in rows
        ]

        # 中断(方案确认卡)仍要看图状态, 读失败不影响历史回显
        interrupt = await self._safe_read_interrupt(thread_id)

        # 接管客服展示名
        claimed_by_name = None
        if chat_thread.claimed_by:
            claimed_by_name = await self.session.scalar(
                select(func.coalesce(AdminUser.display_name, AdminUser.username)).where(
                    AdminUser.id == chat_thread.claimed_by
                )
            )

        return ChatThreadHistoryResponse(
            thread_id=thread_id,
            messages=message_list,
            interrupt=interrupt,
            mode=chat_thread.mode or "ai",
            claimed_by_name=claimed_by_name,
            handoff_note=chat_thread.handoff_note or None,
        )

    async def _safe_read_interrupt(self, thread_id: UUID):
        """读图快照里的中断(方案确认卡); 失败返回 None, 不影响历史回显。"""
        try:
            _config = RunnableConfig(configurable={"thread_id": str(thread_id)})
            snapshot = await self.agent.aget_state(_config)
            interrupts = getattr(snapshot, "interrupts", None)
            if interrupts:
                return interrupts[0].value
            for task in getattr(snapshot, "tasks", None) or []:
                task_interrupts = getattr(task, "interrupts", None)
                if task_interrupts:
                    return task_interrupts[0].value
        except Exception:  # noqa: BLE001 快照读失败不能拖垮历史接口
            return None
        return None