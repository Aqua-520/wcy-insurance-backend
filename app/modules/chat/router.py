"""
    聊天请求的路由层
    接收前端请求体,并且调用与大模型交互的service层
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.params import Header
from fastapi.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.infra.database import get_session
# 导入请求模型
from .schemas import ChatRequestModel
# 服务层类
from .service import ChatService

router = APIRouter(prefix='/api/v1',tags=['大模型调用路由'])

# 依赖注入函数
def init_chat_service(
        # 拿到fastapi的对象
        request:Request,
        # sqlalchemy数据库会话
        session:AsyncSession = Depends(get_session)
):
    # 拿到会话session和request中的agent对象,传入服务层类,实例化操作对象
    return ChatService(session,request.app.state.agent)

@router.post('/chat',summary='发送消息给大模型',response_class=EventSourceResponse)
async def chat(
        # 接收用户id
        user_id: Annotated[int, Header(alias='x-user-id')],
        request: ChatRequestModel,
        # 注入依赖
        service: ChatService = Depends(init_chat_service)
):
    # 调用业务层对象方法,传入请求体和用户id拿到模型结果返回
    # service层返回的也是异步生成器,循环需要加上async
    async for sse in service.chat_service(user_id,request):
        # 返回sse流式片段对象
        yield sse

    #  模拟流式sse调用
    # for i in range(10):
    #     # data存储消息,event标注当前片段的事件类型,fastapi看到返回值为EventSourceResponse,会不断调用此接口函数
    #     # 此函数在遇到yield不断暂停,被fastapi不断调用生成器向前端发送消息,yield执行完毕后走到最后的end
    #     yield ServerSentEvent(data=f'message_{i}',event='message')
    #
    # yield ServerSentEvent(data='[DONE]',event='done')
