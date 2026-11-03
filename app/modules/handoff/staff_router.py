"""人工接管 - 客服工作台路由(仅 cs / admin 岗位)。

- GET    /                     会话队列(等待中 + 我已接管)
- POST   /{thread_id}/claim    原子抢单
- POST   /{thread_id}/messages 客服发消息(进 chat_messages, role=agent)
- POST   /{thread_id}/end      结束会话(必填交接说明, AI 恢复上下文)
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, require_role

from .schemas import (
    AgentMessageRequest,
    AgentSessionListResponse,
    ChatMessagesIncrementalResponse,
    EndSessionRequest,
    EndSessionResponse,
)
from .service import HandoffService

router = APIRouter(
    prefix="/api/v1/admin/sessions",
    tags=["后台管理-人工会话"],
    dependencies=[Depends(require_role("cs"))],
)


def init_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HandoffService:
    # 会话结束时要给图注入交接说明, 需要 app.state.agent
    return HandoffService(session, agent=getattr(request.app.state, "agent", None))


@router.get("", response_model=AgentSessionListResponse, summary="人工会话队列(等待/接管中)")
async def list_sessions(
    mode: Optional[str] = Query(
        default=None, description="逗号分隔: waiting,agent; 缺省两者都返回"
    ),
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    modes = tuple(part.strip() for part in (mode or "waiting,agent").split(",") if part.strip())
    modes = tuple(m for m in modes if m in ("waiting", "agent")) or ("waiting", "agent")
    return await service.list_sessions(modes, admin_id=current.admin_id)


@router.get(
    "/{thread_id}/messages",
    response_model=ChatMessagesIncrementalResponse,
    summary="客服读取会话消息(工作台对话流)",
)
async def staff_messages(
    thread_id: UUID,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    return await service.staff_messages(thread_id, after_id=after_id, limit=limit)


@router.post("/{thread_id}/claim", summary="接入会话(原子抢单, 被抢走返回 409)")
async def claim_session(
    thread_id: UUID,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    # 展示名由服务层统一回查 display_name(客户看到的应是"小王"而不是登录名 cs01)
    return await service.claim(thread_id, current.admin_id)


@router.post("/{thread_id}/messages", summary="客服回复客户(直达聊天框)")
async def send_message(
    thread_id: UUID,
    body: AgentMessageRequest,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    return await service.send_agent_message(thread_id, current.admin_id, None, body.content)


@router.post("/{thread_id}/heartbeat", summary="客服工作台心跳(防静默超时被释放)")
async def heartbeat(
    thread_id: UUID,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    return await service.heartbeat(thread_id, current.admin_id)


@router.post("/{thread_id}/end", response_model=EndSessionResponse, summary="结束人工会话(必填交接说明)")
async def end_session(
    thread_id: UUID,
    body: EndSessionRequest,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: HandoffService = Depends(init_service),
):
    return await service.end_session(thread_id, current.admin_id, body.handoff_note)
