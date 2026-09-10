"""
    本模块来实现闲聊工作流的实现
"""
from typing import NotRequired

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.constants import START, END
from langgraph.graph import StateGraph

from app.core.config import settings
from app.core.logging import get_logger
# 定义子图的state状态类
from .schemas import InsuranceAgentState


logger = get_logger(__name__)

SYSTEM_MESSAGE = """
你是保险智能客服，负责处理与保险业务无关的普通聊天。

要求：
1. 回复友好、自然，最多两句话。
2. 不假装有个人经历、情感、实时信息或外部能力。
3. 不回答医疗、法律、投资等高风险专业建议。
4. 每次回复都自然引导用户回到保险产品、投保或理赔业务。
5. 超出能力范围时，如实说明无法提供。
""".strip()

# 最大闲聊次数
MAX_CHITCHAT_COUNT = 3

class ChitChatState(InsuranceAgentState):
    # 表示非必须key,可以没有这个属性
    chit_chat_count:  NotRequired[int]


class ChitChatGraph:
    def __init__(self):
        # 创建大模型
        llm = init_chat_model(
            model=settings.llm.chat_model,
            api_key=settings.llm.api_key,
            extra_body={"thinking": {"type": "disabled"}},
        )

        self.llm = llm

    # 闲聊节点
    async def handle_chit_chat(self,state: ChitChatState):
        # 闲聊次数
        chit_chat_count = state.get('chit_chat_count',0)

        # 如果上一轮工作流不是闲聊,计数清0
        if state.get('previous_workflow') != 'chit_chat':
            chit_chat_count = 0

        # 判断闲聊次数有没有超过三次,如果超三次直接返回固定信息
        if chit_chat_count > MAX_CHITCHAT_COUNT:
            # 手动构建一个ai消息对象
            return {
                "messages":AIMessage(content='我是小汪助手,我主要协助处理保险产品、投保和理赔咨询，请告诉我想办理或了解的事项。')
            }
        # 调用大模型
        response = await self.llm.ainvoke(
            [
                # 消息列表传入系统消息
                SystemMessage(content=SYSTEM_MESSAGE),
                # 解构所有的历史消息
                *state['messages']  # 将历史消息解包到列表中
            ]
        )
        # 将大模型返回的消息拼入state中
        return {
            'messages': [response], 'chit_chat_count': chit_chat_count + 1
        }

    # 构建子图
    def build(self):
        # 创建builder
        builder = StateGraph(ChitChatState)

        # 添加节点
        builder.add_node("handle_chit_chat",self.handle_chit_chat)

        # 连线
        builder.add_edge(START,"handle_chit_chat")
        builder.add_edge("handle_chit_chat",END)

        # 与父图共享检查点快照
        return builder.compile(checkpointer=True)

    # 初始化子图,拿到子图对象
    @staticmethod
    def init_chit_chat_graph():
        # 子图创建的图对象返回
        return ChitChatGraph().build()