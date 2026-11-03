"""
投保意向单模型。

客户对方案中某个产品感兴趣时提交意向(而非假支付),
生成意向编号, 由客服岗位在后台跟进处理。
未接入保险公司正式投保接口前, 这是唯一的真实"投保"入口。
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class ApplicationIntent(Base, CreateAtMixin, UpdateAtMixin):
    """投保意向单"""

    __tablename__ = "application_intents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intent_no: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="意向申请编号, 对客户展示"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="提交意向的客户",
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        comment="意向产品",
    )
    # 来源方案/方案项, 便于回溯客户是在哪个方案里提交的
    plan_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    plan_item_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    customer_phone: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="客户备注")
    # pending 待跟进 / contacted 已联系 / converted 已转化 / closed 已关闭
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'pending'::character varying"),
        index=True,
        comment="跟进状态: pending / contacted / converted / closed",
    )
    # 跟进该意向的员工
    handled_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="跟进员工",
    )
    handle_note: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="跟进备注")
    # ---- 跟进过程管理(结构化) ----
    next_follow_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="下次跟进时间(SLA 预警依据)"
    )
    follow_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="累计跟进次数"
    )
    last_result: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="最近一次跟进结果标签: interested/waiting/budget/ unreachable/competitor/other",
    )


class IntentFollow(Base, CreateAtMixin):
    """意向跟进记录(时间线)

    每次跟进追加一条, 不覆盖历史: 状态变更(/handle)自动留痕,
    仅沟通不改状态的跟进走 /follows 记一笔(如"电话未接通")。
    """

    __tablename__ = "intent_follows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intent_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("application_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属意向单",
    )
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="跟进员工",
    )
    # 仅记录不改状态的跟进: from_status=to_status=当时状态
    from_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="跟进前状态"
    )
    to_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="跟进后状态(仅记录时与前值相同)"
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="跟进内容")
    # ---- 结构化跟进 ----
    method: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="跟进方式: phone/wechat/meeting/other"
    )
    result: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="结果标签: interested/waiting/budget/unreachable/competitor/other"
    )


class Policy(Base, CreateAtMixin, UpdateAtMixin):
    """保单(成交后延伸) —— 对齐 business-service-baseline 的 policies 表。

    仅做记账, 不是出单: 线下完成投保手续后登记保单信息,
    用于续期提醒与回访管理。真实出单由保险公司承保。
    status: pending 待生效 / active 保障中 / expired 已到期 / terminated 已退保
    """

    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4, comment="保单主键"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_number: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, comment="保单号(线下保司出具)"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'::character varying"),
        comment="pending/active/expired/terminated",
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="保障起期"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="保障止期(续期提醒依据)"
    )
    application_no: Mapped[Optional[str]] = mapped_column(
        String(60), nullable=True, comment="来源投保意向编号(Y-xxx)"
    )
    holder_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="投保人")
    insured_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="被保人")
    insured_id_no_masked: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="被保人证件号(脱敏)"
    )
    insured_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, comment="被保人电话")
    coverage_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True, comment="保额")
    premium_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True, comment="保费")
    payment_frequency: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="缴费频率: annual/semi_annual/quarterly/monthly"
    )
    beneficiary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="受益人信息")
    policy_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="保单快照")
    coverage_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="保障责任快照")
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="缴费时间")
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="出单时间")
