from distutils.cmd import Command
from typing import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.core.config import settings
from app.core.logging import get_logger
# 导入定义的工具
from .tools import query_candidate_products, create_insurance_plan
# 导入context上下文格式规定类型
from .schemas import InsuranceAgentContext

# 日志对象,传入模块名
logger = get_logger(__name__)

# 系统提示词
SYSTEM_PROMPT = """
你是“安心保”的智能保险顾问。
你需要使用专业、准确、容易理解的语言回答用户的保险问题。
当信息不足时，应先向用户追问，不要编造保险产品或保障内容。
"""

# 定义异常处理中间件函数
@wrap_tool_call
async def handle_tool_errors(request: ToolCallRequest, handler: Callable) -> ToolMessage | Command:
    """处理工具执行错误，返回自定义错误消息给模型"""
    try:
        # 所有的工具函数会被这个中间件函数包裹后调用执行
        return await handler(request)
    except Exception as e:
        # 打印错误日志
        logger.error(f'大模型工具执行失败:{e}')

        # 返回异常
        return ToolMessage(
            content=f'工具执行失败:{str(e)}',
            tool_call_id=request.tool_call['id']
        )

# 智能体初始化函数
def init_insurance_agent(checkpointer: AsyncPostgresSaver):
    # 1.初始化模型
    model = init_chat_model(
        model=settings.llm.chat_model,
        api_key=settings.llm.api_key,
        extra_body={"thinking": {"type": "disabled"}},
    )

    # 2.创建Agent
    agent = create_agent(# type: ignore
        model=model,
        tools=[
            # 查询候选产品列表
            query_candidate_products,
            # 保存保险方案
            create_insurance_plan
        ],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        # 声明 Agent 在运行时期望接收的上下文数据结构
        context_schema=InsuranceAgentContext,
        # 配置中间件列表，用于拦截和控制工具调用的生命周期。
        # handle_tool_errors 会包裹工具的执行过程，可在其中实现：
        # - 前置处理（如日志记录、权限检查）
        # - 异常捕获与优雅降级（如工具报错时返回友好提示）
        # - 后置处理（如结果格式化）
        middleware=[
            handle_tool_errors
        ]
    )
    logger.info("保险顾问Agent初始化成功~✅️")
    return agent