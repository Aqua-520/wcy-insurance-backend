"""
知识库管理接口(仅管理员可访问)
"""
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, get_current_admin
from app.rag.jobs import run_ingestion_job

from .schemas import (
    ChunkListResponse,
    DocumentDeleteResponse,
    IngestionJobItem,
    IngestionJobListResponse,
    JobRetryRequest,
    KbDocumentItem,
    KbDocumentListResponse,
    KbUploadResponse,
    ProductKbStats,
    PurgeChunksResponse,
    ReingestRequest,
)
from .service import KbService

router = APIRouter(prefix="/api/v1/admin/kb", tags=["admin-kb"])


# ---------- 文档 ----------
@router.get("/documents", response_model=KbDocumentListResponse, summary="文档列表")
async def list_documents(
    product_id: int | None = Query(default=None),
    doc_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> KbDocumentListResponse:
    return await KbService(session).list_documents(
        product_id=product_id,
        status=doc_status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/documents",
    response_model=KbUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传知识库文档并触发入库",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    product_id: int = Form(...),
    replace_document_id: UUID | None = Form(default=None),
    apply_to_all: bool = Form(default=False),
    force_full: bool = Form(default=False),
    admin: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> KbUploadResponse:
    result = await KbService(session).upload(
        file=file,
        product_id=product_id,
        replace_document_id=replace_document_id,
        apply_to_all=apply_to_all,
        force_full=force_full,
        admin_id=admin.admin_id,
    )
    for job in result.jobs:
        background_tasks.add_task(run_ingestion_job, job.id)
    return result


@router.get(
    "/documents/{document_id}",
    response_model=KbDocumentItem,
    summary="文档详情",
)
async def get_document(
    document_id: UUID,
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> KbDocumentItem:
    return await KbService(session).get_document(document_id)


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档",
)
async def delete_document(
    document_id: UUID,
    force: bool = Query(default=False),
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> DocumentDeleteResponse:
    return await KbService(session).delete_document(document_id, force=force)


# ---------- 入库任务 ----------
@router.get("/jobs", response_model=IngestionJobListResponse, summary="任务列表")
async def list_jobs(
    product_id: int | None = Query(default=None),
    job_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> IngestionJobListResponse:
    return await KbService(session).list_jobs(
        product_id=product_id,
        status=job_status,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=IngestionJobItem, summary="任务详情")
async def get_job(
    job_id: UUID,
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> IngestionJobItem:
    return await KbService(session).get_job(job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=IngestionJobItem,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重试失败任务",
)
async def retry_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    payload: JobRetryRequest | None = None,
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> IngestionJobItem:
    job = await KbService(session).retry_job(
        job_id, force_full=payload.force_full if payload else True
    )
    background_tasks.add_task(run_ingestion_job, job.id)
    return job


# ---------- 产品维度 ----------
@router.post(
    "/products/{product_id}/reingest",
    response_model=IngestionJobItem,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重新入库产品条款",
)
async def reingest_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    payload: ReingestRequest | None = None,
    admin: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> IngestionJobItem:
    job = await KbService(session).reingest(
        product_id,
        force_full=payload.force_full if payload else False,
        admin_id=admin.admin_id,
    )
    background_tasks.add_task(run_ingestion_job, job.id)
    return job


@router.get(
    "/products/{product_id}/stats",
    response_model=ProductKbStats,
    summary="产品知识库统计",
)
async def product_stats(
    product_id: int,
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ProductKbStats:
    return await KbService(session).product_stats(product_id)


@router.get(
    "/products/{product_id}/chunks",
    response_model=ChunkListResponse,
    summary="产品知识块列表",
)
async def list_chunks(
    product_id: int,
    doc_type: str | None = Query(default=None),
    include_content: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ChunkListResponse:
    return await KbService(session).list_chunks(
        product_id,
        doc_type=doc_type,
        include_content=include_content,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/products/{product_id}/chunks",
    response_model=PurgeChunksResponse,
    summary="清空产品知识块(PG + Milvus)",
)
async def purge_chunks(
    product_id: int,
    _: CurrentAdmin = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> PurgeChunksResponse:
    return await KbService(session).purge_chunks(product_id)
