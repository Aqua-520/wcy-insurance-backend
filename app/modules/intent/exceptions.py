"""
投保意向单模块自定义异常
"""
from app.core.exceptions import ApplicationError


class IntentNotFoundError(ApplicationError):
    """意向单不存在"""
    status_code = 404
    code = "intent_not_found"
    message = "意向单不存在"


class IntentForbiddenError(ApplicationError):
    """非本人意向单"""
    status_code = 403
    code = "intent_forbidden"
    message = "无权查看该意向单"


class IntentInvalidStateError(ApplicationError):
    """意向单当前状态不允许该操作"""
    status_code = 409
    code = "intent_invalid_state"
    message = "意向单当前状态不允许该操作"
