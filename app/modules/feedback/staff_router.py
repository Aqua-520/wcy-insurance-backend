"""
后台问答反馈路由(质量中心雏形): 列表 / 归因与改进处理

管理员与知识运营岗位可访问 —— 反馈改进主要是知识与模型质量工作。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, require_role

from .schemas import FeedbackHandleRequest, FeedbackListResponse, FeedbackSummary
from .service import FeedbackService

router = APIRouter(
    prefix="/api/v1/admin/feedbacks",
    tags=["后台管理-质量中心"],
    dependencies=[Depends(require_role("kb"))],
)


def init_service(session: AsyncSession = Depends(get_session)) -> FeedbackService:
    return FeedbackService(session)


@router.get("", response_model=FeedbackListResponse, summary="反馈列表(可按状态/评价筛选)")
async def list_feedbacks(
    status: Optional[str] = Query(default=None),
    rating: Optional[str] = Query(default=None),
    service: FeedbackService = Depends(init_service),
):
    items, total = await service.list_for_staff(status, rating)
    return FeedbackListResponse(
        items=[FeedbackSummary.model_validate(i) for i in items], total=total
    )


@router.post("/{feedback_id}/handle", response_model=FeedbackSummary, summary="归因与改进处理")
async def handle_feedback(
    feedback_id: int,
    body: FeedbackHandleRequest,
    current: CurrentAdmin = Depends(require_role("kb")),
    service: FeedbackService = Depends(init_service),
):
    feedback = await service.handle(
        feedback_id, current.admin_id, body.category, body.status, body.handle_note
    )
    return FeedbackSummary.model_validate(feedback)
