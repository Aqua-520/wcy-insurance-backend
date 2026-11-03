"""工作台(数据首页)路由: GET /api/v1/admin/dashboard, 登录后的待办概览。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.dependencies import CurrentAdmin, require_role
from app.modules.admin.dashboard_service import DashboardService
from app.infra.database import get_session

router = APIRouter(
    prefix="/api/v1/admin/dashboard",
    tags=["admin-dashboard"],
    dependencies=[Depends(require_role("cs", "kb"))],  # 三岗位都能看, 按角色过滤数据
)


def init_service(session: AsyncSession = Depends(get_session)) -> DashboardService:
    return DashboardService(session)


@router.get("", summary="工作台概览(待办计数, 按岗位过滤)")
async def dashboard_overview(
    current: CurrentAdmin = Depends(require_role("cs", "kb")),
    service: DashboardService = Depends(init_service),
):
    return await service.overview(current.role)
