"""
大模型用量台账模型。

每次 LLM 调用记一行(prompt/completion/cached tokens), 费用不落库 ——
按 settings.llm 的单价在查询时估算, DeepSeek 调价只改配置。
"""
from typing import Optional

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin


class LLMUsageLog(Base, CreateAtMixin):
    """一次大模型调用的用量记录"""

    __tablename__ = "llm_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(
        String(40), index=True,
        comment="调用场景: intent_router / chit_chat / insurance_advisor / other",
    )
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, comment="关联会话(可空)"
    )
    # 不设外键保持松耦合(用户删除不影响台账)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="发起用户(可空)")
    model: Mapped[str] = mapped_column(String(80), default="", comment="模型名")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="输入tokens")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="输出tokens")
    cached_tokens: Mapped[int] = mapped_column(
        Integer, default=0, comment="缓存命中的输入tokens(单价更低)"
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="耗时毫秒")
    status: Mapped[str] = mapped_column(String(20), default="ok", comment="ok / error")
