"""
投保意向单业务层

状态机:
    pending 待跟进 --客服联系--> contacted 已联系 --成交--> converted / 未成交--> closed
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import IntentInvalidStateError, IntentNotFoundError
from .models import ApplicationIntent


def _intent_no() -> str:
    """意向申请编号: Y + 日期 + 4位随机, 如 Y20261029-A1B2"""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"Y{day}-{secrets.token_hex(2).upper()}"


class IntentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 客户侧 ----------

    async def create(self, user_id: int, data) -> ApplicationIntent:
        intent = ApplicationIntent(
            intent_no=_intent_no(),
            user_id=user_id,
            product_id=data.product_id,
            plan_id=data.plan_id,
            plan_item_id=data.plan_item_id,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            remark=data.remark,
            status="pending",
        )
        self.session.add(intent)
        # 请求级 session 不会自动提交, 必须显式 commit 否则请求结束即回滚
        await self.session.commit()
        return intent

    async def list_by_user(self, user_id: int) -> list[ApplicationIntent]:
        return list(
            await self.session.scalars(
                select(ApplicationIntent)
                .where(ApplicationIntent.user_id == user_id)
                .order_by(ApplicationIntent.id.desc())
            )
        )

    async def get_owned_by_user(self, intent_id: int, user_id: int) -> ApplicationIntent:
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None or intent.user_id != user_id:
            raise IntentNotFoundError
        return intent

    # ---------- 客服侧 ----------

    async def list_for_staff(
        self, status: str | None = None
    ) -> tuple[list[ApplicationIntent], int]:
        query = select(ApplicationIntent)
        count_query = select(func.count()).select_from(ApplicationIntent)
        if status:
            query = query.where(ApplicationIntent.status == status)
            count_query = count_query.where(ApplicationIntent.status == status)
        total = (await self.session.execute(count_query)).scalar_one()
        intents = list(await self.session.scalars(query.order_by(ApplicationIntent.id.desc())))
        return intents, total

    async def handle(
        self, intent_id: int, admin_id: int, status: str, handle_note: str
    ) -> ApplicationIntent:
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None:
            raise IntentNotFoundError
        # 已转化/已关闭的不再允许改状态, 防止误操作
        if intent.status in ("converted", "closed"):
            raise IntentInvalidStateError("该意向已终态，不能再次更新")
        intent.status = status
        intent.handled_admin_id = admin_id
        if handle_note:
            intent.handle_note = handle_note
        await self.session.commit()
        return intent
