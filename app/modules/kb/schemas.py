"""
知识库管理请求/响应模型
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KbDocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    storage_stem: str
    clause_name: str
    original_filename: str
    source_type: str
    status: str
    file_size: Optional[int] = None
    conversion_error: Optional[str] = None
    uploaded_by_admin_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    bound_product_ids: List[int] = Field(default_factory=list)


class KbDocumentListResponse(BaseModel):
    items: List[KbDocumentItem]
    total: int
    page: int
    page_size: int


class IngestionJobItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    document_id: Optional[UUID] = None
    clause_name: Optional[str] = None
    source_type: Optional[str] = None
    source_path: Optional[str] = None
    status: str
    stage: Optional[str] = None
    progress: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    report: Optional[dict] = None
    force_full: bool = False
    attempts: int = 1
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class IngestionJobListResponse(BaseModel):
    items: List[IngestionJobItem]
    total: int
    page: int
    page_size: int


class KbUploadResponse(BaseModel):
    document: KbDocumentItem
    jobs: List[IngestionJobItem]


class JobRetryRequest(BaseModel):
    force_full: bool = True


class ReingestRequest(BaseModel):
    force_full: bool = False


class ProductKbStats(BaseModel):
    product_id: int
    chunk_count: int = 0
    text_count: int = 0
    table_count: int = 0
    has_markdown: bool = False
    document_id: Optional[UUID] = None
    document_status: Optional[str] = None
    active_job_id: Optional[UUID] = None


class ChunkItem(BaseModel):
    id: UUID
    section_path: List[str] = Field(default_factory=list)
    doc_type: str
    chunk_index: int
    content_hash: str
    content: str


class ChunkListResponse(BaseModel):
    items: List[ChunkItem]
    total: int
    page: int
    page_size: int


class DocumentDeleteResponse(BaseModel):
    deleted: bool
    deleted_files: int = 0
    unbound_product_ids: List[int] = Field(default_factory=list)


class PurgeChunksResponse(BaseModel):
    deleted_chunks: int
    deleted_vectors: bool
    vector_error: Optional[str] = None
