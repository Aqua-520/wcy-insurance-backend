"""
客服侧投保意向跟进路由: 列表/更新跟进状态; 客服(cs)与管理员可访问
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, require_role

from .schemas import IntentHandleRequest, IntentListResponse, IntentSummary
from .service import IntentService

router = APIRouter(
    prefix="/api/v1/admin/application-intents",
    tags=["后台管理-投保意向"],
    dependencies=[Depends(require_role("cs"))],
)


def init_service(session: AsyncSession = Depends(get_session)) -> IntentService:
    return IntentService(session)


@router.get("", response_model=IntentListResponse, summary="投保意向列表(可按状态筛选)")
async def list_intents(
    status: Optional[str] = Query(default=None),
    service: IntentService = Depends(init_service),
):
    intents, total = await service.list_for_staff(status)
    return IntentListResponse(
        items=[IntentSummary.model_validate(i) for i in intents], total=total
    )


@router.post("/{intent_id}/handle", response_model=IntentSummary, summary="更新跟进状态")
async def handle_intent(
    intent_id: int,
    body: IntentHandleRequest,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: IntentService = Depends(init_service),
):
    intent = await service.handle(intent_id, current.admin_id, body.status, body.handle_note)
    return IntentSummary.model_validate(intent)
