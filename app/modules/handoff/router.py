"""人工接管 - 客户侧路由。

挂在 /api/v1/chat-threads 下, 与既有会话接口同一命名空间:
- POST   /{thread_id}/handoff              申请转人工(建 handoff 工单 + 进入排队)
- POST   /{thread_id}/handoff/cancel       取消排队
- GET    /{thread_id}/messages/incremental 增量拉取正文(真相源, 轮询/重连补齐都靠它)
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .schemas import ChatMessagesIncrementalResponse, HandoffResponse
from .service import HandoffService

router = APIRouter(prefix="/api/v1/chat-threads", tags=["人工接管-客户侧"])


def init_service(session: AsyncSession = Depends(get_session)) -> HandoffService:
    return HandoffService(session)


@router.post("/{thread_id}/handoff", response_model=HandoffResponse, summary="申请转人工客服")
async def request_handoff(
    thread_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: HandoffService = Depends(init_service),
):
    return await service.request_handoff(current.user_id, thread_id)


@router.post("/{thread_id}/handoff/cancel", response_model=HandoffResponse, summary="取消转人工排队")
async def cancel_handoff(
    thread_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: HandoffService = Depends(init_service),
):
    return await service.cancel_handoff(current.user_id, thread_id)


@router.get(
    "/{thread_id}/messages/incremental",
    response_model=ChatMessagesIncrementalResponse,
    summary="增量拉取会话消息(含客服消息与系统事件)",
)
async def incremental_messages(
    thread_id: UUID,
    after_id: int = Query(default=0, ge=0, description="上次拿到的最大消息 id"),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    service: HandoffService = Depends(init_service),
):
    return await service.incremental_messages(current.user_id, thread_id, after_id=after_id, limit=limit)
