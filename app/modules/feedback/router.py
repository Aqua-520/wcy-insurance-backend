"""
客户侧问答反馈路由: 提交反馈 / 我的反馈进度 / 确认改进结果
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .schemas import (
    FeedbackConfirmRequest,
    FeedbackCreateRequest,
    FeedbackListResponse,
    FeedbackSummary,
)
from .service import FeedbackService

router = APIRouter(prefix="/api/v1/feedbacks", tags=["问答反馈-客户侧"])


def init_service(session: AsyncSession = Depends(get_session)) -> FeedbackService:
    return FeedbackService(session)


@router.post("", response_model=FeedbackSummary, status_code=201, summary="提交回答反馈")
async def create_feedback(
    body: FeedbackCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: FeedbackService = Depends(init_service),
):
    feedback = await service.create(current.user_id, body)
    return FeedbackSummary.model_validate(feedback)


@router.get("", response_model=FeedbackListResponse, summary="我的反馈进度")
async def list_my_feedbacks(
    current: CurrentUser = Depends(get_current_user),
    service: FeedbackService = Depends(init_service),
):
    items = await service.list_by_user(current.user_id)
    return FeedbackListResponse(
        items=[FeedbackSummary.model_validate(i) for i in items], total=len(items)
    )


@router.post("/{feedback_id}/confirm", response_model=FeedbackSummary, summary="确认改进结果")
async def confirm_feedback(
    feedback_id: int,
    body: FeedbackConfirmRequest,
    current: CurrentUser = Depends(get_current_user),
    service: FeedbackService = Depends(init_service),
):
    feedback = await service.confirm(feedback_id, current.user_id, body.confirm)
    return FeedbackSummary.model_validate(feedback)
