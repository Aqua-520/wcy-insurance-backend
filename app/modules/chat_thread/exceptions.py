"""
当前模块的自定义异常
"""
# 导入我们定义的公共异常父类
from app.core.exceptions import ApplicationError
class ChatThreadNotFoundError(ApplicationError):
    # 在当前会话业务层,重写报错信息
    status_code = 404
    code = 'chat message is not found'
    message = '会话信息未找到,或不属于当前登录用户'