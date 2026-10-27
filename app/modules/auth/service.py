"""
认证业务层: 注册 / 登录
"""
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import InvalidCredentialsError, UserAlreadyExistsError, UserInactiveError
from .models import User
from .repository import UserRepository
from .schemas import LoginRequest, RegisterRequest
from .security import create_access_token, hash_password, verify_password


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = UserRepository(session)

    async def register(self, data: RegisterRequest) -> User:
        """注册新用户。注册入口永远只创建普通客户, 不接受任何角色字段。"""
        user = User(
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            display_name=data.display_name,
            status="active",
        )
        # 查重与插入放在同一事务: 进入前 session 必须是干净的(注册是该请求首次落库)
        async with self.session.begin():
            exists = await self.repository.exists_by_username_or_email(data.username, data.email)
            if exists:
                raise UserAlreadyExistsError
            self.repository.add(user)
        # expire_on_commit=False, 提交后 user.id 仍可用
        return user

    async def login(self, data: LoginRequest) -> User:
        """校验账号密码, 返回用户对象"""
        user = await self.repository.get_by_login(data.username)
        # 用户不存在或密码错误, 统一返回相同提示, 避免账号被枚举
        if user is None or not verify_password(data.password, user.password_hash):
            raise InvalidCredentialsError
        if user.status != "active":
            raise UserInactiveError
        return user

    @staticmethod
    def issue_token(user: User) -> str:
        """为用户签发 access_token。

        scope=user 用于与后台管理员令牌(scope=admin)做域隔离:
        两种账号的 id 会数值碰撞, 不能只靠 id 查表区分。
        """
        return create_access_token(
            user.id,
            extra={"username": user.username, "scope": "user", "realm": "user"},
        )
