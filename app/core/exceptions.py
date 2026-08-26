"""
    定义全局业务代码异常处理父类
"""
class ApplicationError(Exception):
    # 定义自定义异常默认的属性
    # 服务器有问题
    status_code:int = 500
    code:str = '默认报错的异常代码'
    message:str = '你好,当前服务器正忙,请稍后测试'