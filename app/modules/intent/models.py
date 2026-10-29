"""
投保意向单模型。

客户对方案中某个产品感兴趣时提交意向(而非假支付),
生成意向编号, 由客服岗位在后台跟进处理。
未接入保险公司正式投保接口前, 这是唯一的真实"投保"入口。
"""
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Text, text
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
