"""
员工账号管理路由(仅管理员): 列表 / 新建 / 编辑(含重置密码) / 删除。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session

from .dependencies import CurrentAdmin, require_role
from .schemas import (
    AdminUserCreateRequest,
    AdminUserItem,
    AdminUserListResponse,
    AdminUserUpdateRequest,
)
from .user_service import AdminUserService

# require_role() 不传岗位 = 仅管理员; 建号/管人是管理员专属能力
router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["后台管理-员工管理"],
    dependencies=[Depends(require_role())],
)


def init_service(session: AsyncSession = Depends(get_session)) -> AdminUserService:
    return AdminUserService(session)


@router.get("", response_model=AdminUserListResponse, summary="员工列表")
async def list_users(service: AdminUserService = Depends(init_service)):
    users = await service.list_users()
    return AdminUserListResponse(
        items=[AdminUserItem.model_validate(u) for u in users], total=len(users)
    )


@router.post("", response_model=AdminUserItem, status_code=201, summary="新建员工")
async def create_user(
    body: AdminUserCreateRequest,
    service: AdminUserService = Depends(init_service),
):
    admin = await service.create_user(
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        role=body.role,
    )
    return AdminUserItem.model_validate(admin)


@router.patch("/{user_id}", response_model=AdminUserItem, summary="编辑员工(岗位/状态/姓名/重置密码)")
async def update_user(
    user_id: int,
    body: AdminUserUpdateRequest,
    current: CurrentAdmin = Depends(require_role()),
    service: AdminUserService = Depends(init_service),
):
    admin = await service.update_user(
        user_id=user_id,
        operator_id=current.admin_id,
        display_name=body.display_name,
        role=body.role,
        status=body.status,
        password=body.password,
    )
    return AdminUserItem.model_validate(admin)


@router.delete("/{user_id}", summary="删除员工")
async def delete_user(
    user_id: int,
    current: CurrentAdmin = Depends(require_role()),
    service: AdminUserService = Depends(init_service),
):
    await service.delete_user(user_id, current.admin_id)
    return {"deleted": user_id}
