from uuid import UUID

from sqlalchemy import ARRAY, BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin


class ParentChunk(Base, CreateAtMixin):
    """
    条款父块表（升级点2后：一块内容 = 一个父块 = 一个向量，1:1）。

    - id：确定性主键 uuid5(产品+条款+章节路径+块序号)，同一份资料反复入库稳定，
      同时是 Milvus 对应向量的主键，杜绝“子块指向已删父块”的死链。
    - chunk_index：章节内序号（同一 section_path 下从 1 开始）。
    - content_hash：内容指纹（归一化空白后 sha256 前16位），内容不变指纹不变，
      用于增量入库跳过未变化的块。
    - doc_type：text 正文 / table 整张表格（原子保留，不参与硬切分）。
    - visibility：内容可见性预留位，当前全部 public，将来按角色过滤启用。
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

    __table_args__ = (
        Index("idx_parent_chunks_product", "product_id"),
        Index("idx_parent_chunks_product_hash", "product_id", "content_hash"),
    )