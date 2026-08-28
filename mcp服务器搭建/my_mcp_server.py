"""
    搭建一个自定义的mcp服务器
"""
from fastmcp import FastMCP

# 初始化mcp对象
mcp = FastMCP('wcy_tools')

# 获取天气
@mcp.tool()
# 定义装饰器
def get_weather(location:str)-> str:
    """
    获取某地天气
    :param location: 某个地点
    :return: 返回的详情天气
    """
    return f'{location}的天气是:40度超高温'

# 定义装饰器
@mcp.tool()
def current_time():
    """
    获取当前时间的工具
    :return: 返回当前年月日,时分秒的工具
    """
    return '当前时间是:2006-05-20 13:30:30'

# 启动自定义的mcp服务
if __name__ == '__main__':
    # 指定通信方式为本地线程式调用
    mcp.run(transport='stdio')