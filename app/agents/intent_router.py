"""
    意图识别的模块
    封装一些关于意图识别的方法
"""
import re
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from app.core.config import settings
from core.logging import get_logger

from .schemas import RouterResultModel
from langchain_core.messages import SystemMessage

logger = get_logger(__name__)

# 路由前先进行一波是否为寒暄类问题的正则识别,节省token,提高响应速度
# 寒暄类型枚举
SocialIntent = Literal["greeting", "thanks", "goodbye"]
# 寒暄的匹配规则
SOCIAL_PATTERNS = {
    "greeting": (
        r"(你|您)?好(呀|啊|哦)?",
        r"嗨",
        r"哈喽",
        r"hello",
        r"hi",
        r"在吗",
    ),
    "thanks": (
        r"谢谢(你|您)?",
        r"多谢(你|您)?",
        r"感谢(你|您)?",
        r"辛苦了",
    ),
    "goodbye": (
        r"再见",
        r"拜拜",
        r"先这样",
        r"没事了",
    ),
}
# 寒暄的固定回复
SOCIAL_RESPONSES = {
    "greeting": "您好，我是您的保险顾问，可以帮您咨询产品、推荐方案或办理理赔。",
    "thanks": "不客气，后续有保险问题可以随时问我。",
    "goodbye": "好的，后续需要帮助时随时联系我。",
}

# 三个正则匹配函数
def normalize_message(message: str) -> str:
    """
    对用户问题去掉标点符号
    :param message: 用户问题
    :return: 去掉标点符号的结果
    """
    return re.sub(r"[\s，。！？、,.!?~～]", "", message).lower()


def match_social_intent(message: str) -> SocialIntent | None:
    """
    基于用户消息进行正则匹配
    :param message: 用户消息
    :return: 返回匹配结果
    """
    # 先对用户消息取出标点
    normalized = normalize_message(message)
    # 循环匹配规则
    for intent, patterns in SOCIAL_PATTERNS.items():
        # 如果去重的消息匹配到了某一条规则,返回匹配到的类型
        if any(re.fullmatch(pattern, normalized) for pattern in patterns):
            return intent
    return None

def response_by_social_intent(intent: SocialIntent):
    """
    根据匹配到的类型 返回对应的预制菜
    :param intent: 正则匹配到的消息类型
    :return: 返回预制消息
    """
    return SOCIAL_RESPONSES[intent]



# 意图识别系统提示词
SYSTEM_PROMPT = """
你是保险商城智能客服的意图识别节点，请判断用户消息应该交给哪个工作流。

intent只能从以下选项中选择：
- recommendation_plan：保险产品咨询、产品条款、保险推荐、方案管理和投保咨询
- claim：报案、理赔责任、理赔材料、理赔流程和理赔进度
- human_handoff：投诉、高风险问题或用户明确要求人工服务
- chit_chat：与保险业务无关的普通聊天
- fallback：无法判断用户意图
""".strip()

class IntentRouter:
    def __init__(self):
        # 创建大模型
        model = init_chat_model(
            model=settings.llm.chat_model,
            api_key=settings.llm.api_key,
            extra_body={"thinking": {"type": "disabled"}},
        )
        # 将大模型的输出限定为指定类型
        new_model = model.with_structured_output(RouterResultModel)
        # 把结构化输出的大模型新对象绑定到路由实例身上
        self.llm = new_model

    # 意图识别方法
    async def router(self,context: str, user_question: str):
        """
        先根据用户提示词进行正则匹配,如果是寒暄类消息直接返回预制提示词
        :param context: 上下文信息
        :param user_question: 用户提问
        :return: 返回预制菜打招呼|ai识别出来的意图|异常手动意图
        """
        # 意图结果
        social_intent = match_social_intent(user_question)
        # 判断是否拿到了结果
        if social_intent:
            # 如果拿到了结果直接返回预制菜
            return response_by_social_intent(social_intent)

        try:
            result: RouterResultModel = await self.llm.ainvoke( # type: ignore
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(f"历史对话信息：{context}\n用户本轮消息：{user_question}\n"),
                ]
            )
            logger.info("模型意图识别完成", route_result=result)

            # 返回大模型结构化输出的对象
            return result
        except Exception as e:
            logger.exception("模型意图识别失败 %s",)

            # 如果报异常直接手动创建路由结果对象
            result: RouterResultModel =  RouterResultModel(
                intent="fallback",
                reason="模型意图识别失败",
            )
            # 返回意图识别的对象
            return result

# 创建意图路由对象,供别的模块导入
intent_router = IntentRouter()