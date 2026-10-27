"""
后台管理员认证路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session

from .dependencies import CurrentAdmin, get_current_admin
from .schemas import AdminLoginRequest, AdminSummary, AdminTokenResponse
from .service import AdminAuthService

router = APIRouter(prefix="/api/v1/admin/auth", tags=["后台管理-认证"])


async def init_admin_service(session: AsyncSession = Depends(get_session)) -> AdminAuthService:
    return AdminAuthService(session)


@router.post("/login", response_model=AdminTokenResponse, summary="管理员登录")
async def admin_login(
    body: AdminLoginRequest,
    service: AdminAuthService = Depends(init_admin_service),
) -> AdminTokenResponse:
    admin = await service.login(body)
    token = service.issue_token(admin)
    return AdminTokenResponse(
        access_token=token,
        admin=AdminSummary.model_validate(admin),
    )


@router.get("/me", response_model=AdminSummary, summary="当前管理员信息")
async def admin_me(
    current: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminSummary:
    from .repository import AdminRepository

    admin = await AdminRepository(session).get_by_id(current.admin_id)
    if admin is None:
        from .exceptions import AdminTokenInvalidError
        raise AdminTokenInvalidError
    return AdminSummary.model_validate(admin)
