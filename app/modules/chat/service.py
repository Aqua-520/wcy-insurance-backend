"""
    封装业务层功能集合的类
"""
from typing import AsyncIterator

from fastapi.sse import ServerSentEvent
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.stream import CustomTransformer
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.chat_thread.repository import ChatThreadRepository
from .schemas import ChatRequestModel
# 构建上下文对象,保存用户id
from app.agents.schemas import InsuranceAgentContext
# 引用异步事件流合并
from aiostream import stream as astream

class ChatService:
    # 我们需要从路由层的fastapi身上拿到agent对象
    # 和session,sqlalchemy数据库会话对象,进行一些会话信息校验
    def __init__(self,session: AsyncSession,agent: CompiledStateGraph):
        # 通过路由层传来的session,调用会话管理的Repository类,拿到会话管理对象
        self.chat_thread_repository = ChatThreadRepository(session)
        self.agent = agent

    # 调用大模型进行聊天的业务处理函数
    async def chat_service(
            self,
            user_id: int,
            request: ChatRequestModel
                   )-> AsyncIterator[ServerSentEvent]:
        # 这里user_id从路由层传入,不需要Head函数拿到
        # 请求体直接传过来做校验

        chat_thread = await self.chat_thread_repository.get_chat_thread_owner_repository(
            user_id = user_id,
            thread_id = request.thread_id
        )
        # 判断有没有找到
        if chat_thread is None:
            # 如果没查到,抛出异常
            from app.modules.chat_thread.exceptions import ChatThreadNotFoundError
            raise ChatThreadNotFoundError

        # 查到了则基于这个会话id进行模型调用,获取模型的回复
        # invoke需要传入用户最新消息,和历史会话消息的配置

        # 构建用户消息
        _input = {
            "messages":[
                HumanMessage(content = request.message)
            ]
        }
        # 构建会话历史保存配置
        _config = RunnableConfig(configurable={"thread_id": request.thread_id})

        # 将用户id挂载到agent的上下文属性身上,供工具调用
        # 因为这里是业务代码,可以拿到前端会话路由发来的用户id
        _context = InsuranceAgentContext(user_id=user_id)

        # 改成stream流式调用
        # astream_events方法会开启无限循环接收大模型返回的消息,不断地yield吐出chunk
        # 而yield函数又是一个异步生成器,如果需要循环生成器对象,则需要给循环加上async
        stream = await self.agent.astream_events(input=_input,config=_config,version='v3',context=_context,
                                                 transformers=[CustomTransformer])

        # 将stream遍历解包出来,改造成迭代器返回
        # 循环迭代器必须要加async
        async def stream_message():
            """
            拆解大模型返回的迭代器
            :return: 返回给前端做消息页面渲染
            """
            async for content in stream.messages:
                async for text in content.text:
                    # 构造sse对象返回
                    yield ServerSentEvent(data=text, event='message')

        # 通过自定义事件,工具调用返回的查询结果,给前端原封不动发送回去
        async def custom_stream_message():
            """
            发送给前端,工具结果按照格式返回
            前端渲染引用文本
            :return: 工具中writer写入的自定义事件
            """
            async for event in stream.extensions['custom']:
                # 获取事件类型为additional_info自定义名称
                if event.get('type') == 'additional_info':
                    # 返回自定义信息流
                    yield ServerSentEvent(data=event.get('data'), event='additional_info')

        # 合并两个事件流统一输出给前端
        merged = astream.merge(
            stream_message(),
            custom_stream_message()
        )
        # 开启事件流
        async with merged.stream() as stream_message:
            async for event in  stream_message:
                yield event

        # 结束响应
        yield ServerSentEvent(data='[DONE]',event='done')