"""
知识库管理模型。

- KbDocument: 持久文件档案(原始 PDF / Markdown、哈希、转换状态、绑定关系);
- IngestionJob: 一次入库执行事件(状态、阶段、进度、增量报告)。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class KbDocument(Base, CreateAtMixin, UpdateAtMixin):
    """知识库文件档案"""

    __tablename__ = "kb_documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    storage_stem: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    # 与 products.clause_name 对齐: <storage_stem>.pdf 或 <storage_stem>.md
    clause_name: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="pdf / md")
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    markdown_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ready'::character varying"),
        comment="converting / ready / conversion_failed",
    )
    conversion_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_kb_documents_clause_name", "clause_name"),
        Index("idx_kb_documents_status", "status"),
    )


class IngestionJob(Base, CreateAtMixin, UpdateAtMixin):
    """一次知识库入库任务"""

    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    document_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    clause_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'::character varying"),
        comment="pending / processing / succeeded / failed / cancelled",
    )
    stage: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    progress: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("0"),
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    force_full: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    admin_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uk_ingestion_jobs_active_product",
            "product_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
        Index("idx_ingestion_jobs_status_created", "status", "created_at"),
        Index("idx_ingestion_jobs_product", "product_id"),
    )
