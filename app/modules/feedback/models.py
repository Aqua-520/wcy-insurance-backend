"""
问答反馈模型(质量闭环)。

客户对 AI 回答点赞/点踩, 点踩必填原因; 反馈关联当次问答轨迹
(问题原文+回答快照), 供后台归因分析与改进。
"""
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class AnswerFeedback(Base, CreateAtMixin, UpdateAtMixin):
    """AI 回答反馈"""

    __tablename__ = "answer_feedbacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="反馈客户",
    )
    # 关联的咨询会话与问题快照, 便于回溯当次轨迹
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="客户当轮提问")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="AI 回答快照")

    # up 赞 / down 踩
    rating: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="评价: up / down"
    )
    # 点踩原因(赞可以为空)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="点踩原因")

    # 后台归因: retrieval 检索问题 / clause 条款问题 / model 模型问题 / other 其他
    category: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="归因分类: retrieval / clause / model / other",
    )
    # pending 待处理 / improving 改进中 / resolved 已解决 / rejected 不成立
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'pending'::character varying"),
        index=True,
        comment="处理状态: pending / improving / resolved / rejected",
    )
    handle_note: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="后台改进说明"
    )
    handled_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="处理人",
    )
    # 客户对改进结果的确认: accepted 认可 / rejected 不认可 / null 未确认
    customer_confirm: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="客户确认: accepted 认可 / rejected 不认可",
    )
