"""
认证模块自定义异常
"""
from app.core.exceptions import ApplicationError


class InvalidCredentialsError(ApplicationError):
    """用户名或密码错误 / 令牌无效"""
    status_code = 401
    code = "invalid_credentials"
    message = "用户名或密码错误"


class TokenInvalidError(ApplicationError):
    """访问令牌缺失、伪造或过期"""
    status_code = 401
    code = "token_invalid"
    message = "登录状态已失效，请重新登录"


class UserInactiveError(ApplicationError):
    """账号被停用"""
    status_code = 403
    code = "user_inactive"
    message = "账号已被停用，请联系管理员"


class UserAlreadyExistsError(ApplicationError):
    """用户名或邮箱已被注册"""
    status_code = 409
    code = "user_already_exists"
    message = "用户名或邮箱已被注册"
