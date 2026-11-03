"""
保险方案模块自定义异常
"""
from app.core.exceptions import ApplicationError


class InsurancePlanNotFoundError(ApplicationError):
    """方案不存在"""
    status_code = 404
    code = "insurance_plan_not_found"
    message = "保险方案不存在"


class InsurancePlanForbiddenError(ApplicationError):
    """非本人方案"""
    status_code = 403
    code = "insurance_plan_forbidden"
    message = "无权查看该保险方案"


class InsurancePlanConflictError(ApplicationError):
    """方案已进入投保流程, 禁止修改/删除"""
    status_code = 409
    code = "insurance_plan_conflict"
    message = "方案已进入投保流程, 不能修改或删除"
