"""人工接管: 自定义异常。"""
from app.core.exceptions import ApplicationError


class HandoffInvalidStateError(ApplicationError):
    status_code = 409
    code = "handoff.invalid_state"
    message = "当前会话状态不允许该操作"


class SessionNotFoundError(ApplicationError):
    status_code = 404
    code = "handoff.session_not_found"
    message = "会话不存在"


class SessionNotClaimedError(ApplicationError):
    status_code = 403
    code = "handoff.not_claimant"
    message = "请先接入该会话, 否则不能操作"


class SessionAlreadyClaimedError(ApplicationError):
    status_code = 409
    code = "handoff.already_claimed"
    message = "该会话已被其他客服接入"
