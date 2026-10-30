"""
问答反馈业务层

状态机:
    pending 待处理 --后台归因--> improving 改进中 --完成--> resolved 已解决
                                                     --判定不成立--> rejected
    resolved --客户确认--> accepted 认可 / rejected 不认可(回灌成 improving)
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import FeedbackInvalidStateError, FeedbackNotFoundError
from .models import AnswerFeedback


class FeedbackService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 客户侧 ----------

    async def create(self, user_id: int, data) -> AnswerFeedback:
        # 点踩必须填原因
        if data.rating == "down" and not data.reason.strip():
            raise FeedbackInvalidStateError("点踩请填写原因, 便于我们改进")
        feedback = AnswerFeedback(
            user_id=user_id,
            thread_id=data.thread_id,
            question=data.question,
            answer=data.answer,
            rating=data.rating,
            reason=data.reason,
            status="pending",
        )
        self.session.add(feedback)
        await self.session.commit()
        return feedback

    async def list_by_user(self, user_id: int) -> list[AnswerFeedback]:
        return list(
            await self.session.scalars(
                select(AnswerFeedback)
                .where(AnswerFeedback.user_id == user_id)
                .order_by(AnswerFeedback.id.desc())
            )
        )

    async def confirm(self, feedback_id: int, user_id: int, confirm: str) -> AnswerFeedback:
        feedback = await self.session.get(AnswerFeedback, feedback_id)
        if feedback is None or feedback.user_id != user_id:
            raise FeedbackNotFoundError
        if feedback.status != "resolved":
            raise FeedbackInvalidStateError("改进完成后才能确认结果")
        feedback.customer_confirm = confirm
        # 不认可 → 回灌重新改进(清单17: 不认可后须重新评估才能再关)
        if confirm == "rejected":
            feedback.status = "improving"
        await self.session.commit()
        return feedback

    # ---------- 后台侧 ----------

    async def list_for_staff(
        self, status: str | None = None, rating: str | None = None
    ) -> tuple[list[AnswerFeedback], int]:
        query = select(AnswerFeedback)
        count_query = select(func.count()).select_from(AnswerFeedback)
        if status:
            query = query.where(AnswerFeedback.status == status)
            count_query = count_query.where(AnswerFeedback.status == status)
        if rating:
            query = query.where(AnswerFeedback.rating == rating)
            count_query = count_query.where(AnswerFeedback.rating == rating)
        total = (await self.session.execute(count_query)).scalar_one()
        items = list(await self.session.scalars(query.order_by(AnswerFeedback.id.desc())))
        return items, total

    async def handle(
        self,
        feedback_id: int,
        admin_id: int,
        category: str,
        status: str,
        handle_note: str,
    ) -> AnswerFeedback:
        feedback = await self.session.get(AnswerFeedback, feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError
        feedback.category = category
        feedback.status = status
        if handle_note:
            feedback.handle_note = handle_note
        feedback.handled_admin_id = admin_id
        await self.session.commit()
        return feedback
