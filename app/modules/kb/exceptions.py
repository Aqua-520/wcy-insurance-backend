"""
知识库管理模块自定义异常
"""
from app.core.exceptions import ApplicationError


class _MessageError(ApplicationError):
    def __init__(self, message: str | None = None):
        if message:
            self.message = message


class DocumentNotFoundError(ApplicationError):
    status_code = 404
    code = "document_not_found"
    message = "知识库文档不存在"


class DocumentInUseError(_MessageError):
    status_code = 409
    code = "document_in_use"
    message = "文档仍被产品绑定，不能删除"


class InvalidUploadError(_MessageError):
    status_code = 400
    code = "invalid_upload"
    message = "上传文件不合法"


class UploadTooLargeError(_MessageError):
    status_code = 413
    code = "upload_too_large"
    message = "上传文件超过大小限制"


class JobNotFoundError(ApplicationError):
    status_code = 404
    code = "job_not_found"
    message = "入库任务不存在"


class JobNotRetryableError(_MessageError):
    status_code = 409
    code = "job_not_retryable"
    message = "该任务当前状态不允许重试"


class ProductNotBoundError(_MessageError):
    status_code = 409
    code = "product_not_bound"
    message = "产品尚未绑定条款文件"
