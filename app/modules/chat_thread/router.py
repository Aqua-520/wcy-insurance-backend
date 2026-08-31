from uuid import UUID
from fastapi import APIRouter,Header,Depends,status,Response
from typing import Annotated
# 异步消息类
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

# 导入pydantic模型
from .schemas import ChatThreadCreateRequest, ChatThreadCreateResponse, ChatThreadHistoryResponse
# 导入业务层对象,创建对象调用里面的方法操作业务
from .service import ChatThreadService
# 获取数据库连接会话
from app.infra.database import get_session

router = APIRouter(prefix='/api/v1/chat-threads',tags=['聊天会话窗口管理路由'])

# 初始化业务,服务层
async def init_chat_Thread_service(request:Request,session: AsyncSession = Depends(get_session)):
    # 创建业务层对象,
    # 新增一一条agent对象传入
    return ChatThreadService(session=session,agent=request.app.state.agent)


@router.post(path='',response_model=ChatThreadCreateResponse)
# 新建会话的路由函数
async def create_chat_Thread(request_body:ChatThreadCreateRequest,
                             user_id: Annotated[int,Header(alias='x-user-id')],
                             service: ChatThreadService = Depends(init_chat_Thread_service)):
    # 将用户身份信息,响应体聊天标题
    result = await service.add(user_id=user_id,title=request_body.title)

    return result


@router.get('',response_model=list[ChatThreadCreateResponse])
# 查询所有会话列表的路由
async def get_chat_thread_list(user_id: Annotated[int,Header(alias='x-user-id')],
                                service: ChatThreadService = Depends(init_chat_Thread_service)):
    """
    获取消息列表的函数
    :param user_id: 前端请求头传入用户id
    :param service: 传入业务层操作对象,注入依赖
    :return: 返回会话消息列表
    """
    result = await service.get_chat_thread_list_service(user_id=user_id)
    return result

@router.patch('/{thread_id}',response_model=ChatThreadCreateResponse)
# 修改某一条会话的路由
async def update_chat_thread_title(
        request_body: ChatThreadCreateRequest,
        thread_id: UUID,
        user_id: Annotated[int, Header(alias='x-user-id')],
        service: ChatThreadService = Depends(init_chat_Thread_service)
):
    """
    修改会话title的接口
    :param request_body:
    :param user_id:
    :param thread_id:
    :param service: 传入业务层操作对象,注入依赖
    :return: 返回最新的会话对象回去
    """
    return await service.update_chat_thread_service(thread_id=thread_id,user_id=user_id,title=request_body.title)


@router.delete('/{thread_id}',status_code=status.HTTP_204_NO_CONTENT)
# 删除某一条会话记录的路由
async def delete_chat_thread(
        thread_id: UUID,
        user_id: Annotated[int,Header(alias='x-user-id')],
        service: ChatThreadService = Depends(init_chat_Thread_service)
):
    # 将路由收到的参数传递给下一层进行处理
    await service.delete_chat_thread_owner_service(thread_id,user_id)

    # 直接返回一个状态码即可
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 回显聊天对话详情的接口
@router.get('/{thread_id}/messages',summary='查询指定会话的历史消息',response_model=ChatThreadHistoryResponse)
async def get_chat_content(
        # 前端传入会话id
        thread_id: UUID,
        # 用户唯一标识id
        user_id: Annotated[int, Header(alias='x-user-id')],
        # 注入业务层对象
        service: ChatThreadService = Depends(init_chat_Thread_service)
):
    # 接收会话id做回显，根据user_id查一把看看
    return await service.get_chat_content_service(user_id,thread_id)
