"""
后台管理模块自定义异常
"""
from app.core.exceptions import ApplicationError


class InvalidAdminCredentialsError(ApplicationError):
    """管理员用户名或密码错误"""
    status_code = 401
    code = "invalid_admin_credentials"
    message = "管理员用户名或密码错误"


class AdminTokenInvalidError(ApplicationError):
    """管理员令牌缺失、伪造、过期或不是管理员令牌"""
    status_code = 401
    code = "admin_token_invalid"
    message = "管理员登录状态已失效，请重新登录"


class AdminInactiveError(ApplicationError):
    """管理员账号被停用"""
    status_code = 403
    code = "admin_inactive"
    message = "管理员账号已被停用"


class AdminForbiddenError(ApplicationError):
    """当前岗位无权访问该接口"""
    status_code = 403
    code = "admin_forbidden"
    message = "当前岗位无权执行该操作"


class _MessageError(ApplicationError):
    """允许在抛出时覆盖默认 message 的业务异常基类"""

    def __init__(self, message: str | None = None):
        if message:
            self.message = message


class ProductNotFoundError(ApplicationError):
    """产品不存在"""
    status_code = 404
    code = "product_not_found"
    message = "产品不存在"


class ProductInUseError(_MessageError):
    """产品存在业务引用, 不能硬删除"""
    status_code = 409
    code = "product_in_use"
    message = "产品已被业务数据引用，请改用下架"


class ProductHasActiveJobError(ApplicationError):
    """产品有运行中的入库任务"""
    status_code = 409
    code = "product_has_active_job"
    message = "产品有正在执行的入库任务，请等待完成后再操作"


class ProductInvalidStateError(_MessageError):
    """产品状态或条款文件不满足操作条件"""
    status_code = 409
    code = "product_invalid_state"
    message = "产品当前状态不允许该操作"


class ProductValidationError(_MessageError):
    """编辑产品的跨字段校验失败"""
    status_code = 422
    code = "invalid_product_fields"
    message = "产品字段校验失败"


class DocumentNotFoundError(ApplicationError):
    """知识库文档不存在"""
    status_code = 404
    code = "document_not_found"
    message = "知识库文档不存在"


class DocumentInUseError(ApplicationError):
    """文档仍被产品绑定"""
    status_code = 409
    code = "document_in_use"
    message = "文档仍被产品绑定，不能删除"
