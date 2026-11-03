"""用量监控接口(后台): 汇总/按日/按场景统计 + DeepSeek 余额代理。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import require_role

from .service import UsageService

router = APIRouter(
    prefix="/api/v1/admin/usage",
    tags=["后台管理-用量监控"],
    dependencies=[Depends(require_role("kb"))],  # 知识运营与管理员可见
)


def init_service(session: AsyncSession = Depends(get_session)) -> UsageService:
    return UsageService(session)


@router.get("/summary", summary="用量汇总(近N天)")
async def usage_summary(
    days: int = Query(default=7, ge=1, le=90),
    service: UsageService = Depends(init_service),
):
    return await service.summary(days)


@router.get("/daily", summary="按日用量(近N天)")
async def usage_daily(
    days: int = Query(default=30, ge=1, le=90),
    service: UsageService = Depends(init_service),
):
    items = await service.daily(days)
    return {"items": items, "total": len(items)}


@router.get("/by-scene", summary="按场景用量(近N天)")
async def usage_by_scene(
    days: int = Query(default=7, ge=1, le=90),
    service: UsageService = Depends(init_service),
):
    items = await service.by_scene(days)
    return {"items": items, "total": len(items)}


@router.get("/quality", summary="在线质量指标(满意度/归因/错误率/耗时)")
async def usage_quality(
    days: int = Query(default=7, ge=1, le=90),
    service: UsageService = Depends(init_service),
):
    return await service.quality(days)


@router.get("/balance", summary="DeepSeek 账户余额(带5分钟缓存)")
async def usage_balance():
    return await UsageService.balance()
