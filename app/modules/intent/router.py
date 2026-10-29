"""
客户侧投保意向路由: 提交意向 / 我的意向列表
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .schemas import IntentCreateRequest, IntentListResponse, IntentSummary
from .service import IntentService

router = APIRouter(prefix="/api/v1/application-intents", tags=["投保意向-客户侧"])


def init_service(session: AsyncSession = Depends(get_session)) -> IntentService:
    return IntentService(session)


@router.post("", response_model=IntentSummary, status_code=201, summary="提交投保意向")
async def create_intent(
    body: IntentCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: IntentService = Depends(init_service),
):
    intent = await service.create(current.user_id, body)
    return IntentSummary.model_validate(intent)


@router.get("", response_model=IntentListResponse, summary="我的投保意向")
async def list_my_intents(
    current: CurrentUser = Depends(get_current_user),
    service: IntentService = Depends(init_service),
):
    intents = await service.list_by_user(current.user_id)
    return IntentListResponse(
        items=[IntentSummary.model_validate(i) for i in intents], total=len(intents)
    )
