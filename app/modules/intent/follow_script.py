"""
跟进话术草稿: 结合意向信息/产品/跟进历史, 为专员生成本次跟进话术。

预填给专员确认修改后使用, 不自动外呼/自动发送(合规红线)。
失败直接抛给路由层, 由它转成 502 —— 草稿生成失败必须显式告知, 不静默。
"""
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.modules.usage.callbacks import usage_collector

SYSTEM_PROMPT = (
    "你是保险经纪公司的销售培训专家。请根据客户意向与跟进历史, 生成一条本次跟进的话术草稿。\n"
    "要求: 中文口语化、自然称呼客户、100字以内、不承诺收益、不诋毁同业、"
    "不编造条款细节(具体数字以条款为准)、结尾给出下一步动作(如约定时间/发送资料)。\n"
    "只输出话术本身, 不要解释。"
)


async def build_follow_script(
    intent, follows: list[dict], product_name: str | None = None
) -> str:
    """生成跟进话术草稿。LLM 失败向上抛, 由路由层转 502。"""
    llm = init_chat_model(
        model=settings.llm.chat_model,
        api_key=settings.llm.api_key,
        extra_body={"thinking": {"type": "disabled"}},
        # 用量进台账; stream_usage 让流式回答也带 token 用量
        callbacks=[usage_collector("follow_script")],
        stream_usage=True,
    )
    history_lines = [
        f"- {f.get('note') or ''}" for f in follows[-5:] if f.get("note")
    ]
    history = "\n".join(history_lines) or "(暂无跟进记录)"
    human = (
        f"客户: {intent.customer_name}\n"
        f"意向产品: {product_name or f'产品ID {intent.product_id}'}\n"
        f"客户备注: {intent.remark or '(无)'}\n"
        f"当前状态: {intent.status}\n"
        f"跟进历史(近5条):\n{history}\n"
        "请生成本次跟进话术草稿。"
    )
    result = await llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human)]
    )
    content = result.content
    return content if isinstance(content, str) else str(content)
