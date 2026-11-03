"""
方案路由: 只读查询 + 方案项投保状态流转(转已投保)。

GET 供前端刷新方案项投保状态与浏览「我的方案」列表, 只返回本人方案;
结构按前端 extractPlanItems 约定: 顶层 items 数组, 每项含 id / product_id / status。
PATCH /{plan_id}/items/{item_id}/insured 对应前端 markPlanItemInsured:
客户线下完成投保手续后确认"已投保"; 客服标记意向"已转化"时也会自动联动到此状态。
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .exceptions import (
    InsurancePlanConflictError,
    InsurancePlanNotFoundError,
    InsurancePlanForbiddenError,
)
from .models import InsurancePlan, InsurancePlanItem
from .repository import InsurancePlanRepository
from .schemas import InsurancePlanUpdate

router = APIRouter(prefix="/api/v1/insurance-plans", tags=["保险方案"])


def _serialize_plan(plan: InsurancePlan) -> dict:
    return {
        "id": str(plan.id),
        "plan_name": plan.plan_name,
        "summary": plan.summary,
        "status": plan.status,
        "annual_premium_budget": plan.annual_premium_budget,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "items": [
            {
                "id": str(item.id),
                "product_id": item.product_id,
                "priority": item.priority,
                "recommendation_reason": item.recommendation_reason,
                "annual_premium_budget": item.annual_premium_budget,
                "status": item.status,
            }
            for item in plan.items
        ],
    }


@router.get("", summary="我的方案列表(含方案项状态)")
async def list_plans(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    plans = (
        await session.scalars(
            select(InsurancePlan)
            .options(selectinload(InsurancePlan.items))
            .where(InsurancePlan.user_id == current.user_id)
            .order_by(InsurancePlan.id.desc())
        )
    ).all()
    return {"items": [_serialize_plan(plan) for plan in plans], "total": len(plans)}


@router.get("/{plan_id}", summary="查询本人保险方案(含方案项状态)")
async def get_plan(
    plan_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    plan = await session.scalar(
        select(InsurancePlan)
        .options(selectinload(InsurancePlan.items))
        .where(InsurancePlan.id == plan_id)
    )
    if plan is None:
        raise InsurancePlanNotFoundError
    if plan.user_id != current.user_id:
        raise InsurancePlanForbiddenError
    return _serialize_plan(plan)


@router.patch(
    "/{plan_id}/items/{item_id}/insured",
    summary="转已投保(标记方案项已投保)",
)
async def mark_item_insured(
    plan_id: str,
    item_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """客户线下完成投保手续后确认"已投保"。

    幂等: 重复标记返回当前状态不报错。方案级状态自动汇总
    (全部方案项已投保 -> 方案已投保; 任一投保中/已投保 -> 投保中)。
    """
    try:
        plan_uuid, item_uuid = UUID(plan_id), UUID(item_id)
    except ValueError:
        raise InsurancePlanNotFoundError
    repository = InsurancePlanRepository(session)
    pair = await repository.get_plan_item(plan_uuid, item_uuid)
    if pair is None:
        raise InsurancePlanNotFoundError
    plan, item = pair
    if plan.user_id != current.user_id:
        raise InsurancePlanForbiddenError
    item.status = "insured"
    plan_status = await repository.sync_plan_status(plan_uuid)
    # 请求级 session 不会自动提交, 显式 commit 否则请求结束即回滚
    await session.commit()
    return {
        "item_id": str(item.id),
        "status": item.status,
        "plan_id": str(plan.id),
        "plan_status": plan_status,
    }


@router.patch("/{plan_id}", summary="修改方案(名称/说明)")
async def update_plan(
    plan_id: str,
    payload: InsurancePlanUpdate,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        plan_uuid = UUID(plan_id)
    except ValueError:
        raise InsurancePlanNotFoundError
    plan = await session.scalar(
        select(InsurancePlan).where(InsurancePlan.id == plan_uuid)
    )
    if plan is None:
        raise InsurancePlanNotFoundError
    if plan.user_id != current.user_id:
        raise InsurancePlanForbiddenError
    if payload.plan_name is not None:
        plan.plan_name = payload.plan_name
    if payload.summary is not None:
        plan.summary = payload.summary
    # commit 后 refresh, 避免 onupdate 字段懒加载触发 MissingGreenlet
    await session.commit()
    await session.refresh(plan)
    return {
        "plan_id": str(plan.id),
        "plan_name": plan.plan_name,
        "summary": plan.summary,
    }


@router.delete("/{plan_id}", summary="删除方案(仅未进入投保流程)")
async def delete_plan(
    plan_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """删除方案及其全部方案项。

    业务红线: 任一方案项已投保中/已投保, 或方案已产生投保意向 -> 409 不能删
    (成交与售后需要留痕, 不能靠删数据抹掉)。
    """
    try:
        plan_uuid = UUID(plan_id)
    except ValueError:
        raise InsurancePlanNotFoundError
    plan = await session.scalar(
        select(InsurancePlan)
        .options(selectinload(InsurancePlan.items))
        .where(InsurancePlan.id == plan_uuid)
    )
    if plan is None:
        raise InsurancePlanNotFoundError
    if plan.user_id != current.user_id:
        raise InsurancePlanForbiddenError
    if any(item.status != "uninsured" for item in plan.items):
        raise InsurancePlanConflictError("方案中已有产品进入投保流程, 不能删除")

    from app.modules.intent.models import ApplicationIntent

    # 注意: application_intents.plan_id/plan_item_id 是 String(64) 存 uuid 文本,
    # 必须用字符串比较, 直接比 UUID 会类型不匹配报 500
    item_ids = [str(item.id) for item in plan.items]
    refs = await session.scalar(
        select(func.count())
        .select_from(ApplicationIntent)
        .where(
            (ApplicationIntent.plan_id == str(plan_uuid))
            | (ApplicationIntent.plan_item_id.in_(item_ids))
        )
    )
    if refs:
        raise InsurancePlanConflictError("方案已产生投保意向, 不能删除")

    for item in list(plan.items):
        await session.delete(item)
    await session.delete(plan)
    await session.commit()
    return {"deleted": True, "plan_id": plan_id}


@router.delete("/{plan_id}/items/{item_id}", summary="从方案中移除产品(仅未投保)")
async def delete_plan_item(
    plan_id: str,
    item_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        plan_uuid, item_uuid = UUID(plan_id), UUID(item_id)
    except ValueError:
        raise InsurancePlanNotFoundError
    repository = InsurancePlanRepository(session)
    pair = await repository.get_plan_item(plan_uuid, item_uuid)
    if pair is None:
        raise InsurancePlanNotFoundError
    plan, item = pair
    if plan.user_id != current.user_id:
        raise InsurancePlanForbiddenError
    if item.status != "uninsured":
        raise InsurancePlanConflictError("该产品已进入投保流程, 不能移除")
    await session.delete(item)
    plan_status = await repository.sync_plan_status(plan_uuid)
    await session.commit()
    return {
        "deleted": True,
        "item_id": item_id,
        "plan_id": plan_id,
        "plan_status": plan_status,
    }
