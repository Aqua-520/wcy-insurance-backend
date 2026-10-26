"""
    聊天请求的路由层
    接收前端请求体,并且调用与大模型交互的service层
"""
from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user
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
        request: ChatRequestModel,
        # 从登录令牌解析当前用户, 不再信任请求头
        current: CurrentUser = Depends(get_current_user),
        # 注入依赖
        service: ChatService = Depends(init_chat_service)
):
    # 调用业务层对象方法,传入可信的用户id和请求体,拿到模型结果返回
    # service层返回的也是异步生成器,循环需要加上async
    async for sse in service.chat_service(current.user_id, request):
        # 返回sse流式片段对象
        yield sse
