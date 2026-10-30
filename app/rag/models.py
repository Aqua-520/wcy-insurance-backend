from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base, CreateAtMixin


class ParentChunk(Base, CreateAtMixin):
    """
    条款父块表（升级点2后：一块内容 = 一个父块 = 一个向量，1:1）。

    - id：确定性主键 uuid5(产品+条款+章节路径+块序号)，同一份资料反复入库稳定，
      同时是 Milvus 对应向量的主键，杜绝"子块指向已删父块"的死链。
    - chunk_index：章节内序号（同一 section_path 下从 1 开始）。
    - content_hash：内容指纹（归一化空白后 sha256 前16位），内容不变指纹不变，
      用于增量入库跳过未变化的块。
    - doc_type：text 正文 / table 整张表格（原子保留，不参与硬切分）。
    - visibility：内容可见性预留位，当前全部 public，将来按角色过滤启用。
    - is_published：发布状态，入库后默认 false（候选），审核发布后 AI 才能检索到。
    """

    __tablename__ = "parent_chunks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(BigInteger)
    clause_name: Mapped[str] = mapped_column(String(300))
    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
    )
    content: Mapped[str] = mapped_column(Text)

    # —— 升级点2/3 新增字段 ——
    chunk_index: Mapped[int] = mapped_column(BigInteger, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    doc_type: Mapped[str] = mapped_column(String(20), default="text")
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    # 发布状态: false=候选(未发布), true=已发布(AI可检索)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )

    __table_args__ = (
        Index("idx_parent_chunks_product", "product_id"),
        Index("idx_parent_chunks_product_hash", "product_id", "content_hash"),
        Index("idx_parent_chunks_published", "is_published"),
    )


class KbRelease(Base, CreateAtMixin):
    """知识库发布记录: 每次发布/撤回生成一条, 留审计轨迹"""

    __tablename__ = "kb_releases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # draft / published / retracted
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'draft'::character varying"),
        comment="发布状态: draft / published / retracted",
    )
    # 谁构建(上传/入库)的
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="构建人(上传/入库操作者)",
    )
    # 谁发布的(不能是构建人自己)
    published_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="发布人(不能与构建人相同)",
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retracted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="备注")

    __table_args__ = (
        Index("idx_kb_releases_product_status", "product_id", "status"),
    )