"""
工单模块自定义异常
"""
from app.core.exceptions import ApplicationError


class TicketNotFoundError(ApplicationError):
    """工单不存在"""
    status_code = 404
    code = "ticket_not_found"
    message = "工单不存在"


class TicketForbiddenError(ApplicationError):
    """无权操作该工单(非本人工单或岗位不符)"""
    status_code = 403
    code = "ticket_forbidden"
    message = "无权操作该工单"


class TicketInvalidStateError(ApplicationError):
    """工单当前状态不允许该操作"""
    status_code = 409
    code = "ticket_invalid_state"
    message = "工单当前状态不允许该操作"
