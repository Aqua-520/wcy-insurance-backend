"""
    我们这个模块来实现编排器主图的创建和管理
"""
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import Command

from app.core.logging import get_logger

from .chit_chat import ChitChatGraph
from .schemas import InsuranceAgentState, RouterResultModel, Intent

logger = get_logger(__name__)
from langgraph.constants import START, END
"""
    以下都为子图导入
"""
# 导入路由识别对象
from .intent_router import intent_router
from .insurance_advisor import init_insurance_agent

# 获取ai消息的函数
def find_final_ai_message(messages_state: list[BaseMessage]) -> str:
    # 接收所有的消息列表
    # 先将消息列表做截取,获取到新的消息列表,不然反转函数反转的是原消息列表
    for message in reversed(messages_state[:-1]):
        # 判断每一条消息的所属
        if not isinstance(message,AIMessage):
            # 如果不是ai消息直接跳过本轮循环
            continue

        # 如果是ai消息,判断是不是工具调用消息
        if message.tool_calls:
            # 是工具调用消息,也要跳过
            continue
        # 有ai消息,不为空,返回
        if message.content:
            return message.content

    return ''



# 明确要求人工的说法: 命中就不用再花一次模型调用去判意图
_HANDOFF_PHRASES = (
    "转人工",
    "人工客服",
    "真人客服",
    "找客服",
    "人工服务",
    "转接人工",
    "要人工",
    "叫人工",
)


def wants_human(text: str) -> bool:
    content = (text or "").strip()
    if not content:
        return False
    return any(phrase in content for phrase in _HANDOFF_PHRASES)


# 定义意图识别节点
async def router(state: InsuranceAgentState) -> Command[Intent]:
    # 获取上一次的工作流名称和本次
    # 如果是第一次执行上一次和当前应该都为空
    old_active  =  state.get('active_workflow','')

    # 关键词快路: "转人工/人工客服"这类明确诉求直接进人工节点,
    # 不让模型去猜(省一次调用, 也避免被判成 chit_chat/fallback)
    if wants_human(state["messages"][-1].text):
        return Command(
            update={
                "previous_workflow": old_active,
                "active_workflow": "human_handoff",
            },
            goto="human_handoff",
        )


    # 调用方法来获取到本轮意图识别该走的工作流节点名称
    # 编写需要传入的上下文信息,这里我们简化,把大模型上一轮的返回信息直接丢回去
    final_ai_message = find_final_ai_message(state['messages'])
    context = f"上一轮的工作流节点名称是:{old_active},上一轮ai返回的消息是:{final_ai_message}"

    # 获取意图
    intent_result = await intent_router.router(
        # 将拼接好的上下文信息传入识别节点
        context=context,
        user_question=state["messages"][-1].text
    )
    # 如果用户输入的是寒暄,直接返回设定好的预制菜回复
    if isinstance(intent_result,str):
        return Command(
            update={
                "previous_workflow": old_active,
                "active_workflow": 'chit_chat',
                # 手动构建ai消息对象
                'messages': [AIMessage(content=intent_result)]
            },
            # 直接结束
            goto=END
        )

    # 不是寒暄字符串,则代表拿到的结构化输出对象
    # 使用Command进行节点转发
    return Command(
        update={
            "previous_workflow": old_active,
            # 本轮的意图识别结果
            "active_workflow": intent_result.intent
        },
        # intent则为本轮大模型返回的意图识别结果
        # 去往下一个节点
        goto=intent_result.intent
    )

# 2.闲聊节点
# async def chit_chat_node(state: InsuranceAgentState) -> dict:
#     return {"messages": [AIMessage("你好，今天想聊点什么？")]}


# 3.保险推荐节点
# async def recommendation_node(state: InsuranceAgentState) -> dict:
#     return {"messages": [AIMessage("保险推荐工作流暂未接入。")]}


# 4.理赔节点: 真实创建理赔咨询工单, 由客服跟进
async def claim_node(state: InsuranceAgentState) -> dict:
    ticket_no = await _create_ticket_for_current_turn("claim", state)
    if ticket_no:
        return {"messages": [AIMessage(
            f"已为你创建理赔咨询工单，受理编号 {ticket_no}。"
            "客服领取后会尽快与你联系，你也可以在「我的」中补充材料。"
        )]}
    return {"messages": [AIMessage("工单创建失败，请稍后重试，或直接留言申请人工服务。")]}


# 5.人工节点: 投诉/高风险/明确要求人工 → 统一工单模型
async def human_handoff_node(state: InsuranceAgentState) -> dict:
    """真正把会话切到人工(排队/留言), 而不是只开一张票。

    2026-11-03 修复: 原来这里只建工单并回"已为你转接人工", 会话 mode 不变,
    客户打字"转人工"后 AI 继续答、聊天框里也没有客服接管 —— 按钮和打字两条路
    走的是完全不同的逻辑。现在统一走 HandoffService.request_handoff。
    """
    from langchain_core.runnables import RunnableConfig
    from langgraph.config import get_config  # type: ignore[attr-defined]
    from langgraph.runtime import get_runtime

    from app.infra.database import AsyncSessionFactory
    from app.modules.handoff.service import HandoffService
    from .schemas import InsuranceAgentContext

    user_id: int | None = None
    thread_id: str | None = None
    try:
        runtime = get_runtime(InsuranceAgentContext)
        user_id = runtime.context.user_id if runtime.context else None
    except Exception:
        user_id = None
    try:
        config: RunnableConfig = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
    except Exception:
        thread_id = None

    if user_id is None or thread_id is None:
        return {"messages": [AIMessage("我这边暂时无法转接人工，请稍后再试或直接提交投诉工单。")]}

    try:
        async with AsyncSessionFactory() as session:
            result = await HandoffService(session, agent=None).request_handoff(
                user_id=user_id,
                thread_id=thread_id,
                system_notice=False,  # 由本条 AI 回复承载文案, 不重复插系统消息
            )
        notice = str(result.get("notice") or "")
        ticket_no = result.get("ticket_no")
        if result.get("mode") == "agent":
            return {"messages": [AIMessage(notice or "客服已经在与你沟通中。")]}
        if ticket_no:
            return {"messages": [AIMessage(f"{notice}（受理编号 {ticket_no}）")]}
        return {"messages": [AIMessage(notice or "已为你转接人工服务。")]}
    except Exception:
        logger.exception("聊天转人工失败, 降级为建工单")
        ticket_no = await _create_ticket_for_current_turn("handoff", state)
        if ticket_no:
            return {"messages": [AIMessage(
                f"已为你登记人工服务请求，受理编号 {ticket_no}。客服会尽快跟进。"
            )]}
        return {"messages": [AIMessage("转人工请求提交失败，请稍后重试。")]}


async def _create_ticket_for_current_turn(ticket_type: str, state: InsuranceAgentState) -> str | None:
    """给当前用户+当前会话创建(或复用)一张工单, 返回受理编号。

    用户身份来自路由层注入的运行时上下文; 拿不到身份时不建单, 不报错中断对话。
    """
    from langchain_core.runnables import RunnableConfig
    from langgraph.config import get_config  # type: ignore[attr-defined]
    from langgraph.runtime import get_runtime

    from app.infra.database import AsyncSessionFactory
    from app.modules.ticket.service import TicketService
    from .schemas import InsuranceAgentContext

    try:
        runtime = get_runtime(InsuranceAgentContext)
        user_id: int | None = runtime.context.user_id if runtime.context else None
    except Exception:
        user_id = None
    if user_id is None:
        return None

    # 用户最新一条消息作为工单摘要, 供客服判断诉求
    summary = ""
    for message in reversed(state.get("messages", [])):
        if message.type == "human" and message.content:
            summary = str(message.content)[:500]
            break

    try:
        config: RunnableConfig = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        # config 里的 thread_id 可能是 UUID 对象, 统一成字符串再落库
        if thread_id is not None:
            thread_id = str(thread_id)
        async with AsyncSessionFactory() as session:
            # 服务内部自带 commit, 这里不能再包 session.begin()
            ticket = await TicketService(session).create_from_ai(
                user_id=user_id,
                ticket_type=ticket_type,
                summary=summary,
                thread_id=thread_id,
            )
            return ticket.ticket_no
    except Exception:
        logger.exception("创建人工工单失败")
        return None


# 6.fallback节点
def fallback_node(state: InsuranceAgentState) -> dict:
    return {"messages": [AIMessage("我还不能确定你的需求，请说明是想咨询保险、推荐方案还是办理理赔。")]}

# 开始创建智能体工作流
def init_router_agent(checkpointer: AsyncPostgresSaver):
    # 创建builder
    graph_builder = StateGraph(InsuranceAgentState)

    # 添加节点
    graph_builder.add_node("router",router)

    # 添加子节点
    graph_builder.add_node("chit_chat",ChitChatGraph.init_chit_chat_graph()) # 闲聊子图
    graph_builder.add_node("recommendation_plan",init_insurance_agent()) # 保险方案推荐子图
    graph_builder.add_node("claim",claim_node)
    graph_builder.add_node("human_handoff",human_handoff_node)
    graph_builder.add_node("fallback",fallback_node)

    # 使用边进行节点连接
    # 开始到router节点,节点直接走到下一步
    graph_builder.add_edge(START, 'router')

    # 下一步的节点直接走向end,最后invoke会输出state状态字典的信息
    graph_builder.add_edge('chit_chat', END)
    graph_builder.add_edge('recommendation_plan', END)
    graph_builder.add_edge('claim', END)
    graph_builder.add_edge('human_handoff', END)
    graph_builder.add_edge('fallback', END)

    # 编译图指定checkpointer并返回
    return graph_builder.compile(checkpointer=checkpointer)


