"""
认证路由: 注册 / 登录 / 当前用户
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session

from .dependencies import CurrentUser, get_current_user
from .repository import UserRepository
from .schemas import LoginRequest, RegisterRequest, TokenResponse, UserSummary
from .service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["认证鉴权"])


def init_auth_service(session: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(session)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED,
             summary="用户注册(注册成功直接签发令牌)")
async def register(
    body: RegisterRequest,
    service: AuthService = Depends(init_auth_service),
) -> TokenResponse:
    user = await service.register(body)
    token = service.issue_token(user)
    return TokenResponse(access_token=token, user=UserSummary.model_validate(user))


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(
    body: LoginRequest,
    service: AuthService = Depends(init_auth_service),
) -> TokenResponse:
    user = await service.login(body)
    token = service.issue_token(user)
    return TokenResponse(access_token=token, user=UserSummary.model_validate(user))


@router.get("/me", response_model=UserSummary, summary="获取当前登录用户")
async def me(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserSummary:
    user = await UserRepository(session).get_by_id(current.user_id)
    return UserSummary.model_validate(user)
