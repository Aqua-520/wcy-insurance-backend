# 数据库sqlalchemy数据模型
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    String,
    Text,
    Numeric,
    ARRAY,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# 假设你的基础类是这样的，包含 id、created_at、updated_at
# 如果基础类里没有 id，可以在这里定义
from app.common.models import Base, CreateAtMixin, UpdateAtMixin  # 替换为你的基础类实际导入路径


class Product(Base,CreateAtMixin,UpdateAtMixin):
    """保险商城在售及历史保险产品"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="商城展示名称"
    )
    clause_name: Mapped[str] = mapped_column(
        String(300), nullable=False, comment="主条款文件名，包含 .pdf 后缀"
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="险种分类：医疗、重疾、意外或寿险",
    )
    insurer: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="承保保险公司"
    )
    image_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="产品展示图片地址"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="产品简介"
    )
    min_premium: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True, comment="产品公开的最低年缴保费参考"
    )
    max_premium: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True, comment="产品公开的最高保费参考，可为空"
    )
    target_group: Mapped[Optional[str]] = mapped_column(
        String(300), nullable=True, comment="适用人群说明"
    )
    highlights: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String), nullable=True, comment="产品亮点列表"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'active'::character varying"),
        comment="产品状态",
    )

    # 表级约束和索引
    __table_args__ = (
        CheckConstraint(
            "category::text = ANY (ARRAY['medical'::character varying, "
            "'critical_illness'::character varying, "
            "'accident'::character varying, "
            "'life'::character varying])",
            name="chk_products_category",
        ),
        Index("idx_products_category", "category"),
        Index("idx_products_status", "status"),
        # 如果基础类没有指定表注释，可以在这里添加
        # {"comment": "保险商城在售及历史保险产品"},
    )