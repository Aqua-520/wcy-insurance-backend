from uuid import UUID

from sqlalchemy import select, and_, func, update

from .models import ChatMessage, ChatThread


def _as_uuid(value):
    """会话 id 统一成 UUID 对象: 路由/pydantic 可能给 str, asyncpg 的 uuid 列不接受 str。"""
    return value if isinstance(value, UUID) else UUID(str(value))


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

    # ---------- 消息(业务真相源) ----------

    async def add_message(
        self,
        thread_id,
        role: str,
        content: str,
        *,
        message_type: str = "text",
        sender_admin_id: int | None = None,
        sender_admin_name: str | None = None,
        additional_info: dict | None = None,
        client_msg_id: str | None = None,
    ) -> ChatMessage:
        """追加一条消息并 flush(拿到自增 id); 事务提交由调用方决定。"""
        message = ChatMessage(
            thread_id=_as_uuid(thread_id),
            role=role,
            content=content or "",
            message_type=message_type,
            sender_admin_id=sender_admin_id,
            sender_admin_name=sender_admin_name,
            additional_info=additional_info,
            client_msg_id=client_msg_id,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_messages(self, thread_id, after_id: int = 0, limit: int = 200) -> list[ChatMessage]:
        """增量拉取: id > after_id 按 id 升序, 供前端补齐/轮询使用。"""
        result = await self.session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == _as_uuid(thread_id), ChatMessage.id > after_id)
            .order_by(ChatMessage.id.asc())
            .limit(limit)
        )
        return list(result.all())

    async def count_messages(self, thread_id) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.thread_id == _as_uuid(thread_id))
            )
            or 0
        )

    async def latest_message(self, thread_id) -> ChatMessage | None:
        return await self.session.scalar(
            select(ChatMessage)
            .where(ChatMessage.thread_id == _as_uuid(thread_id))
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )

    # ---------- 接管状态(并发安全) ----------

    async def claim_thread(self, thread_id, admin_id: int) -> bool:
        """原子抢单: 条件 UPDATE, 两个客服同时点只有一个成功。

        返回 False 表示已被他人接管 / 已不在排队态。
        """
        result = await self.session.execute(
            update(ChatThread)
            .where(
                ChatThread.id == _as_uuid(thread_id),
                ChatThread.mode == "waiting",
                ChatThread.claimed_by.is_(None),
            )
            .values(
                mode="agent",
                claimed_by=admin_id,
                claimed_at=func.now(),
                agent_seen_at=func.now(),
                mode_changed_at=func.now(),
                updated_at=func.now(),
            )
            .returning(ChatThread.id)
        )
        return result.scalar_one_or_none() is not None