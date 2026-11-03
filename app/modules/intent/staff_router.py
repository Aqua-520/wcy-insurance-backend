"""
客服侧投保意向跟进路由: 列表/更新跟进状态/结构化跟进/话术草稿/保单登记;
客服(cs)与管理员可访问
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, require_role
from app.modules.product.repository import Product

from .exceptions import IntentScriptError
from .follow_script import build_follow_script
from .schemas import (
    IntentFollowCreate,
    IntentFollowItem,
    IntentHandleRequest,
    IntentListResponse,
    IntentSummary,
    PolicyRegisterRequest,
)
from .service import IntentService, is_overdue

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
        items=[
            IntentSummary.model_validate(i).model_copy(update={"overdue": is_overdue(i)})
            for i in intents
        ],
        total=total,
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


@router.get("/{intent_id}/follows", summary="意向跟进时间线(客服查看)")
async def list_intent_follows(
    intent_id: int,
    service: IntentService = Depends(init_service),
):
    follows = await service.list_follows(intent_id)
    return {"items": follows, "total": len(follows)}


@router.post(
    "/{intent_id}/follows",
    response_model=IntentFollowItem,
    status_code=201,
    summary="记录一次跟进(不改状态)",
)
async def add_intent_follow(
    intent_id: int,
    body: IntentFollowCreate,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: IntentService = Depends(init_service),
):
    """仅记录一次跟进沟通(如"电话未接通"), 不改意向状态, 追加进时间线。"""
    follow = await service.add_follow(
        intent_id,
        current.admin_id,
        body.note,
        method=body.method,
        result=body.result,
        next_follow_at=body.next_follow_at,
    )
    return IntentFollowItem(
        id=follow.id,
        from_status=follow.from_status,
        to_status=follow.to_status,
        note=follow.note,
        method=follow.method,
        result=follow.result,
        admin_id=follow.admin_id,
        created_at=follow.created_at,
    )


@router.post(
    "/{intent_id}/draft-script",
    summary="AI 生成跟进话术草稿(预填给专员确认, 不外呼不自动发)",
)
async def draft_follow_script(
    intent_id: int,
    service: IntentService = Depends(init_service),
):
    intent = await service.get(intent_id)
    follows = await service.list_follows(intent_id)
    product_name = None
    if intent.product_id:
        product_name = await service.session.scalar(
            select(Product.name).where(Product.id == intent.product_id)
        )
    try:
        script = await build_follow_script(intent, follows, product_name)
    except Exception as exc:  # LLM 失败显式报错, 不静默给空稿
        raise IntentScriptError from exc
    return {"script": script}


@router.post(
    "/{intent_id}/policy",
    summary="保单登记(仅已成交意向; 线下完成投保手续后记账, 非出单)",
    status_code=201,
)
async def register_policy(
    intent_id: int,
    body: PolicyRegisterRequest,
    service: IntentService = Depends(init_service),
):
    policy = await service.register_policy(intent_id, body)
    return {
        "id": str(policy.id),
        "policy_number": policy.policy_number,
        "status": policy.status,
        "application_no": policy.application_no,
        "effective_at": policy.effective_at.isoformat() if policy.effective_at else None,
        "expires_at": policy.expires_at.isoformat() if policy.expires_at else None,
    }
