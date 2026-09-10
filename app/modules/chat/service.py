"""
    封装业务层功能集合的类
"""
from typing import AsyncIterator

from fastapi.sse import ServerSentEvent
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from langgraph.stream import CustomTransformer
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.chat_thread.repository import ChatThreadRepository
from .schemas import ChatRequestModel
# 构建上下文对象,保存用户id
# 引用状态类,存储条款引用数据
from app.agents.schemas import InsuranceAgentContext,AdditionalInfoData
# 引用异步事件流合并
# from aiostream import stream as astream
from app.core.logging import get_logger

logger = get_logger(__name__)

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
                   ) -> AsyncIterator[ServerSentEvent]:
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
        # 判断一下本轮是否有中断恢复的字段,有则代表需要用户输入决策了
        if request.decision:
            # 这里是langgraph.types这个模块下封装的Command
            _input = Command(resume=request.decision)
        else:
            # 构建普通用户消息,准备调用聊天大模型
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

        # # 将stream遍历解包出来,改造成迭代器返回
        # # 循环迭代器必须要加async
        # async def stream_message():
        #     """
        #     拆解大模型返回的迭代器
        #     :return: 返回给前端做消息页面渲染
        #     """
        #     async for content in stream.messages:
        #         async for text in content.text:
        #             # 构造sse对象返回
        #             yield ServerSentEvent(data=text, event='message')
        #
        # # 通过自定义事件,工具调用返回的查询结果,给前端原封不动发送回去
        # async def custom_stream_message():
        #     """
        #     发送给前端,工具结果按照格式返回
        #     前端渲染引用文本
        #     :return: 工具中writer写入的自定义事件
        #     """
        #     async for event in stream.extensions['custom']:
        #         # 获取事件类型为additional_info自定义名称
        #         if event.get('type') == 'additional_info':
        #             # 返回自定义信息流
        #             yield ServerSentEvent(data=event.get('data'), event='additional_info')
        #
        # # 合并两个事件流统一输出给前端
        # merged = astream.merge(
        #     stream_message(),
        #     custom_stream_message()
        # )
        # # 开启事件流
        # async with merged.stream() as stream_message:
        #     async for event in  stream_message:
        #         yield event

        # 定义两个变量,存储每一次渲染流开始的id,用于区分每个引用的归属聊天流
        final_message_id: str|None = None
        # 定义字典来copy一份引用信息存到state中,state会自动调用checkpointer完成数据库持久化保存
        additional_info_data: AdditionalInfoData = {}
        # 自定义解析事件流
        async for event_dict in stream:
            """
                stream是一个迭代器
                每次循环拿到的是一个字典
            """
            # 判断事件类型
            method = event_dict['method']
            # langgraph封装的消息事件叫messages
            if method == 'messages':
                # 解析里面的数据
                data = event_dict['params']['data'][0]
                if isinstance(data,AIMessage):
                    # 如果第一条为手动构建的Ai消息,也就是我们要返回的固定消息,直接响应给前端
                    yield ServerSentEvent(data=data.text,event='message') # 消息类型给前端做渲染用,data为消息内容
                elif data.get('delta','') and data.get('delta').get('text'):
                    # 这里是系统自动构建的消息,是一个字典,delta这个key里面的文本才是图封装的消息
                    yield ServerSentEvent(data=data.get('delta').get('text'),event='message')
                # 抓取流起始id
                elif data.get('event') == 'message-start' and data.get('id'):
                    final_message_id = data.get('id')

            # 解析自定义消息类型
            if method == 'custom':
                # 将里面的data拿过来
                data = event_dict['params']['data']
                # 解析事件类型
                if data.get('type') == 'additional_info':
                    # 如果是这个事件,获取数据返回给前端
                    # copy一份到变量里,存储到状态中
                    additional_info_data = data.get('data')
                    # 前端需要识别事件流event == additional_info做渲染
                    yield ServerSentEvent(data=additional_info_data,event='additional_info')

        # 检测中断,内部是抛出自定义异常的形式来中断函数的
        interrupts = await stream.interrupts()
        if interrupts:
            logger.info(f'事件中断:{interrupts},需要用户进行手动操作了')
            # 将中断信息以 SSE 事件推送给前端，等待用户输入/确认
            for item in interrupts:
                # 这个item.value刚好就是interrupt函数的入参数据
                yield ServerSentEvent(data=item.value,event='interrupt')


        # 抄一份返回给前端的引用,将工具自定义事件引用数据持久化保存到checkpointer
        if not interrupts and final_message_id and additional_info_data:
            # 这两个都被赋值,有数据,推入图中做state更新操作
            await self.agent.aupdate_state(
                # config区分会话id
                config=_config,
                # 存一个字典,通过state的追加做更新操作
                values={
                    "additional_info":{
                        final_message_id:additional_info_data
                    }
                }
            )

        # 结束响应
        yield ServerSentEvent(data='[DONE]',event='done')