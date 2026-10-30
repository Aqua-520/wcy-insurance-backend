"""
问答反馈模块自定义异常
"""
from app.core.exceptions import ApplicationError


class FeedbackNotFoundError(ApplicationError):
    """反馈不存在"""
    status_code = 404
    code = "feedback_not_found"
    message = "反馈不存在"


class FeedbackInvalidStateError(ApplicationError):
    """反馈当前状态不允许该操作(含点踩未填原因)"""
    status_code = 409
    code = "feedback_invalid_state"
    message = "反馈当前状态不允许该操作"
