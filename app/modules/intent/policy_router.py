"""客户侧保单查询: GET /api/v1/policies (我的保单)"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .service import IntentService

router = APIRouter(prefix="/api/v1/policies", tags=["保单"])


@router.get("", summary="我的保单列表(成交登记后的保单记账)")
async def list_my_policies(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    policies = await IntentService(session).list_policies(current.user_id)
    return {
        "items": [
            {
                "id": str(p.id),
                "policy_number": p.policy_number,
                "status": p.status,
                "product_id": p.product_id,
                "application_no": p.application_no,
                "holder_name": p.holder_name,
                "insured_name": p.insured_name,
                "effective_at": p.effective_at.isoformat() if p.effective_at else None,
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                "coverage_amount": p.coverage_amount,
                "premium_amount": p.premium_amount,
                "payment_frequency": p.payment_frequency,
            }
            for p in policies
        ],
        "total": len(policies),
    }
