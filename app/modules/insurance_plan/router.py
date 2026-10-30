"""
方案查询路由(只读): 供前端刷新方案项投保状态与浏览「我的方案」列表。

只返回本人方案; 结构按前端 extractPlanItems 约定: 顶层 items 数组,
每项含 id / product_id / status。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .exceptions import InsurancePlanNotFoundError, InsurancePlanForbiddenError
from .models import InsurancePlan

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
