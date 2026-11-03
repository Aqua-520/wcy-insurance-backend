"""
投保意向单业务层

状态机:
    pending 待跟进 --客服联系--> contacted 已联系 --成交--> converted / 未成交--> closed

方案投保状态联动(方案项 uninsured/applying/insured):
    提交意向(带方案项)        -> 方案项"投保中"
    跟进标记 converted 已转化 -> 方案项"已投保"(成交即记账), 方案状态按汇总刷新
    跟进标记 closed 已关闭    -> 无其他在途意向时方案项回退"未投保"

跟进记录: /handle 状态变更自动留痕, 仅沟通不改状态走 add_follow 记一笔,
历史只追加不覆盖, 客户可查看自己意向的跟进进展。
"""
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AdminUser
from app.modules.insurance_plan.repository import InsurancePlanRepository

from .exceptions import IntentInvalidStateError, IntentNotFoundError
from .models import ApplicationIntent, IntentFollow, Policy

# SLA: 新单 24 小时无任何跟进即算超时
OVERDUE_HOURS = 24


def is_overdue(intent: ApplicationIntent) -> bool:
    """SLA 超时判定: 在途意向(pending/contacted) 且 (已过下次跟进时间 或 24h 无任何跟进)"""
    if intent.status not in ("pending", "contacted"):
        return False
    now = datetime.now(timezone.utc)

    def _aware(dt: datetime | None) -> datetime | None:
        return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt

    nxt = _aware(intent.next_follow_at)
    if nxt is not None:
        return nxt < now
    if (intent.follow_count or 0) == 0:
        created = _aware(intent.created_at)
        if created is not None:
            return (now - created).total_seconds() > OVERDUE_HOURS * 3600
    return False


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
        # 联动: 关联方案项转"投保中"(解析失败/非本人方案静默跳过, 不影响意向主流程)
        link = await self._load_linked_item(data.plan_id, data.plan_item_id, user_id)
        if link is not None:
            plan, item, repository = link
            if item.status == "uninsured":
                item.status = "applying"
                await repository.sync_plan_status(plan.id)
        # 请求级 session 不会自动提交, 必须显式 commit 否则请求结束即回滚
        await self.session.commit()
        return intent

    async def get(self, intent_id: int) -> ApplicationIntent:
        """按 id 取意向, 不存在抛 404"""
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None:
            raise IntentNotFoundError
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
        old_status = intent.status
        intent.status = status
        intent.handled_admin_id = admin_id
        if handle_note:
            intent.handle_note = handle_note
        # 成交/关闭联动方案投保状态
        await self._sync_linked_plan(intent, status)
        # 状态变更自动留痕进跟进时间线
        self.session.add(
            IntentFollow(
                intent_id=intent.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=status,
                note=handle_note or "",
            )
        )
        await self.session.commit()
        # updated_at 由 onupdate=func.now() 服务端生成, UPDATE 后不会自动回填,
        # 不刷新的话序列化时懒加载会 MissingGreenlet
        await self.session.refresh(intent)
        return intent

    # ---------- 跟进记录(时间线) ----------

    async def add_follow(
        self,
        intent_id: int,
        admin_id: int,
        note: str,
        method: str | None = None,
        result: str | None = None,
        next_follow_at: datetime | None = None,
    ) -> IntentFollow:
        """仅记录一次跟进(不改状态); 结构化字段并回写到意向单"""
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None:
            raise IntentNotFoundError
        follow = IntentFollow(
            intent_id=intent.id,
            admin_id=admin_id,
            from_status=intent.status,
            to_status=intent.status,
            note=note,
            method=method,
            result=result,
        )
        self.session.add(follow)
        # 跟进过程管理: 次数/结果标签/下次跟进时间
        intent.follow_count = (intent.follow_count or 0) + 1
        if result:
            intent.last_result = result
        if next_follow_at is not None:
            intent.next_follow_at = next_follow_at
        await self.session.commit()
        await self.session.refresh(follow)
        return follow

    async def list_follows(
        self, intent_id: int, user_id: int | None = None
    ) -> list[dict]:
        """跟进时间线(按时间正序)。传 user_id 时校验意向归属, 非本人一律 404"""
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None or (user_id is not None and intent.user_id != user_id):
            raise IntentNotFoundError
        rows = await self.session.execute(
            select(IntentFollow, AdminUser.display_name)
            .join(AdminUser, AdminUser.id == IntentFollow.admin_id, isouter=True)
            .where(IntentFollow.intent_id == intent_id)
            .order_by(IntentFollow.id.asc())
        )
        return [
            {
                "id": follow.id,
                "from_status": follow.from_status,
                "to_status": follow.to_status,
                "note": follow.note,
                "method": follow.method,
                "result": follow.result,
                "admin_id": follow.admin_id,
                "admin_name": admin_name,
                "created_at": follow.created_at,
            }
            for follow, admin_name in rows.all()
        ]

    # ---------- 保单登记(成交后延伸) ----------

    async def register_policy(self, intent_id: int, data) -> Policy:
        """保单登记: 仅已成交(converted)意向可登记; 线下完成投保手续后记账, 非出单。"""
        intent = await self.session.get(ApplicationIntent, intent_id)
        if intent is None:
            raise IntentNotFoundError
        if intent.status != "converted":
            raise IntentInvalidStateError("仅已成交的意向可以登记保单")
        if intent.user_id is None or intent.product_id is None:
            raise IntentInvalidStateError("该意向缺少关联客户或产品, 无法登记保单")
        exists = await self.session.scalar(
            select(func.count()).select_from(Policy).where(
                Policy.policy_number == data.policy_number
            )
        )
        if exists:
            raise IntentInvalidStateError("保单号已存在")
        policy = Policy(
            user_id=intent.user_id,
            product_id=intent.product_id,
            policy_number=data.policy_number,
            status="active",
            effective_at=data.effective_at,
            expires_at=data.expires_at,
            application_no=intent.intent_no,
            holder_name=data.holder_name,
            insured_name=data.insured_name,
            insured_phone=data.insured_phone,
            coverage_amount=data.coverage_amount,
            premium_amount=data.premium_amount,
            payment_frequency=data.payment_frequency,
            beneficiary=data.beneficiary,
            issued_at=datetime.now(timezone.utc),
        )
        self.session.add(policy)
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def list_policies(self, user_id: int) -> list[Policy]:
        """我的保单(按保障起期倒序)"""
        return list(
            await self.session.scalars(
                select(Policy)
                .where(Policy.user_id == user_id)
                .order_by(Policy.effective_at.desc())
            )
        )

    # ---------- 方案投保状态联动(内部) ----------

    async def _load_linked_item(self, plan_id_raw, plan_item_id_raw, user_id):
        """解析并校验意向关联的方案项。

        解析失败、方案/方案项不存在、非本人方案都返回 None —— 联动静默跳过,
        不影响意向单主流程。返回 (plan, item, repository)。
        """
        if not plan_id_raw or not plan_item_id_raw or user_id is None:
            return None
        try:
            plan_uuid = UUID(str(plan_id_raw))
            item_uuid = UUID(str(plan_item_id_raw))
        except (ValueError, TypeError):
            return None
        repository = InsurancePlanRepository(self.session)
        pair = await repository.get_plan_item(plan_uuid, item_uuid)
        if pair is None:
            return None
        plan, item = pair
        if plan.user_id != user_id:
            return None
        return plan, item, repository

    async def _sync_linked_plan(self, intent: ApplicationIntent, status: str) -> None:
        """跟进终态联动方案项: converted -> 已投保; closed -> 回退未投保"""
        link = await self._load_linked_item(
            intent.plan_id, intent.plan_item_id, intent.user_id
        )
        if link is None:
            return
        plan, item, repository = link
        if status == "converted":
            item.status = "insured"
            await repository.sync_plan_status(plan.id)
        elif status == "closed":
            if item.status == "applying":
                # 还有其他在途意向(待跟进/已联系)时不回退
                active = await self.session.scalar(
                    select(func.count())
                    .select_from(ApplicationIntent)
                    .where(
                        ApplicationIntent.plan_item_id == intent.plan_item_id,
                        ApplicationIntent.id != intent.id,
                        ApplicationIntent.status.in_(("pending", "contacted")),
                    )
                )
                if not active:
                    item.status = "uninsured"
                    await repository.sync_plan_status(plan.id)
