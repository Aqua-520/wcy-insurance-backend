"""
知识库入库任务执行器。

执行模型:
- API 只负责插入 ingestion_jobs(pending) 并提交 BackgroundTasks;
- 本模块用独立 DB session 更新状态, 用进程内 Semaphore 串行执行;
- PDF 走 MinerU + DeepSeek 清洗, 再复用 RAGPipeline 做增量入库。
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, select, update

from app.core.config import APP_ROOT, settings
from app.core.logging import get_logger
from app.infra.database import AsyncSessionFactory
from app.modules.kb.models import IngestionJob, KbDocument
from app.modules.product.models import Product

from .models import ParentChunk

from .clients import close_vector_store, create_vector_store
from .converters import ConversionError, convert_pdf_to_markdown
from .maintenance import purge_product_knowledge
from .pipeline import RAGPipeline

logger = get_logger(__name__)

# 所有入库任务串行, 避免 MinerU / Ollama / Milvus 同时承压
_SEMAPHORE = asyncio.Semaphore(1)

STAGE_PROGRESS = {
    "queued": 5,
    "purging": 10,
    "converting": 15,
    "cleaning": 30,
    "splitting": 35,
    "writing": 60,
    "embedding": 80,
    "done": 100,
}
STAGE_MESSAGES = {
    "queued": "任务已开始",
    "purging": "正在清理旧知识块",
    "converting": "正在调用 MinerU 解析 PDF",
    "cleaning": "正在调用大模型清洗 Markdown",
    "splitting": "正在切分条款",
    "writing": "正在写入 PostgreSQL",
    "embedding": "正在生成向量并写入 Milvus",
    "done": "入库完成",
}


def _markdown_path(clause_name: str) -> Path:
    return settings.storage.md_dir / f"{Path(clause_name).stem}.md"


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


async def _set_job(job_id: UUID, **values) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                update(IngestionJob).where(IngestionJob.id == job_id).values(**values)
            )


async def _set_document(document_id: UUID, **values) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                update(KbDocument).where(KbDocument.id == document_id).values(**values)
            )


async def _stage_callback(job_id: UUID, stage: str) -> None:
    await _set_job(
        job_id,
        stage=stage,
        progress=STAGE_PROGRESS.get(stage, 50),
        message=STAGE_MESSAGES.get(stage),
    )


async def _load_job_snapshot(job_id: UUID):
    async with AsyncSessionFactory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return None
        if job.status != "pending":
            return None

        product = await session.get(Product, job.product_id) if job.product_id else None
        document = (
            await session.get(KbDocument, job.document_id)
            if job.document_id
            else None
        )

        return SimpleNamespace(
            id=job.id,
            product_id=job.product_id,
            product_name=job.product_name,
            document_id=job.document_id,
            clause_name=job.clause_name,
            source_type=job.source_type,
            source_path=job.source_path,
            force_full=job.force_full,
            product=SimpleNamespace(
                id=product.id if product else job.product_id,
                name=product.name if product else job.product_name,
                clause_name=(
                    document.clause_name
                    if document is not None
                    else (product.clause_name if product else job.clause_name)
                ),
            )
            if (product or document)
            else None,
            document=(
                SimpleNamespace(
                    id=document.id,
                    clause_name=document.clause_name,
                    source_type=document.source_type,
                    source_path=document.source_path,
                    markdown_path=document.markdown_path,
                )
                if document is not None
                else None
            ),
        )


async def run_ingestion_job(job_id: UUID) -> None:
    """执行一个入库任务; 所有异常都落库为 failed, 不向外抛"""
    async with _SEMAPHORE:
        snapshot = await _load_job_snapshot(job_id)
        if snapshot is None:
            return

        # CAS: 只有 pending 才能进入 processing, 避免重复执行
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    update(IngestionJob)
                    .where(
                        IngestionJob.id == job_id,
                        IngestionJob.status == "pending",
                    )
                    .values(
                        status="processing",
                        stage="queued",
                        progress=STAGE_PROGRESS["queued"],
                        message=STAGE_MESSAGES["queued"],
                        started_at=func.now(),
                    )
                )
                if result.rowcount == 0:
                    return

        vector_store = None
        current_stage = "queued"

        async def _on_stage(stage: str) -> None:
            nonlocal current_stage
            current_stage = stage
            await _stage_callback(job_id, stage)

        try:
            if snapshot.product is None or not snapshot.product.clause_name:
                raise ValueError("产品或条款文件不存在，任务无法执行")

            product_view = snapshot.product

            # 重建只刷新内容, 不动发布开关:
            # 入库前记录该产品是否处于"已发布"状态, 入库成功后恢复。
            # 生效中的知识库重建后继续生效; 从未发布的保持候选。
            was_published = False
            if snapshot.product_id:
                async with AsyncSessionFactory() as _s:
                    was_published = bool(
                        await _s.scalar(
                            select(func.count())
                            .select_from(ParentChunk)
                            .where(
                                ParentChunk.product_id == snapshot.product_id,
                                ParentChunk.is_published == True,  # noqa: E712
                            )
                            .limit(1)
                        )
                    )

            if snapshot.force_full and snapshot.product_id:
                current_stage = "purging"
                await _stage_callback(job_id, "purging")
                await purge_product_knowledge(snapshot.product_id)

            # PDF 且 Markdown 尚不存在 -> 先转换
            if (
                snapshot.document is not None
                and snapshot.document.source_type == "pdf"
                and not _markdown_path(product_view.clause_name).exists()
            ):
                pdf_path = (APP_ROOT / snapshot.document.source_path).resolve()
                if not pdf_path.exists():
                    raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

                await _set_document(
                    snapshot.document.id,
                    status="converting",
                    conversion_error=None,
                )
                try:
                    await convert_pdf_to_markdown(
                        pdf_path,
                        _markdown_path(product_view.clause_name),
                        on_stage=_on_stage,
                    )
                except ConversionError as exc:
                    await _set_document(
                        snapshot.document.id,
                        status="conversion_failed",
                        conversion_error=_error_text(exc),
                    )
                    raise
                await _set_document(snapshot.document.id, status="ready")

            vector_store = create_vector_store()
            pipeline = RAGPipeline(vector_store)

            report = await pipeline.product_info_to_store(
                product_view,  # type: ignore[arg-type]
                on_stage=_on_stage,
            )

            # 重建前处于已发布状态的, 入库后恢复发布(内容更新但开关不变);
            # 从未发布过的保持候选, 等人工发布审核。
            if was_published and snapshot.product_id:
                async with AsyncSessionFactory() as _s:
                    async with _s.begin():
                        await _s.execute(
                            update(ParentChunk)
                            .where(ParentChunk.product_id == snapshot.product_id)
                            .values(is_published=True)
                        )
                logger.info(
                    "重建前处于已发布状态, 已恢复发布",
                    product_id=snapshot.product_id,
                )

            # 入库成功后才把产品指向新条款
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    if snapshot.product_id and snapshot.document is not None:
                        await session.execute(
                            update(Product)
                            .where(Product.id == snapshot.product_id)
                            .values(clause_name=snapshot.document.clause_name)
                        )
                    if snapshot.document is not None:
                        await session.execute(
                            update(KbDocument)
                            .where(KbDocument.id == snapshot.document.id)
                            .values(status="ready", conversion_error=None)
                        )
                    await session.execute(
                        update(IngestionJob)
                        .where(IngestionJob.id == job_id)
                        .values(
                            status="succeeded",
                            stage="done",
                            progress=100,
                            message=STAGE_MESSAGES["done"],
                            report=dict(report),
                            finished_at=func.now(),
                        )
                    )
        except Exception as exc:
            logger.exception("入库任务失败", job_id=str(job_id), stage=current_stage)
            error_text = _error_text(exc)
            await _set_job(
                job_id,
                status="failed",
                stage=current_stage,
                error=error_text,
                finished_at=func.now(),
            )
            # PDF 转换未产出 Markdown 时, 同步文档状态, 避免一直停在 converting
            if (
                snapshot.document is not None
                and snapshot.product is not None
                and snapshot.document.source_type == "pdf"
                and not _markdown_path(snapshot.product.clause_name).exists()
            ):
                await _set_document(
                    snapshot.document.id,
                    status="conversion_failed",
                    conversion_error=error_text,
                )
        finally:
            if vector_store is not None:
                await asyncio.to_thread(close_vector_store, vector_store)


async def recover_interrupted_jobs() -> None:
    """应用启动时把因重启中断的任务标记为失败, 并修复文档状态。"""
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                update(IngestionJob)
                .where(IngestionJob.status.in_(("pending", "processing")))
                .values(
                    status="failed",
                    error="服务重启导致任务中断，请重试",
                    finished_at=func.now(),
                )
            )

            documents = (
                await session.scalars(
                    select(KbDocument).where(KbDocument.status == "converting")
                )
            ).all()
            for document in documents:
                markdown_exists = (APP_ROOT / document.markdown_path).exists()
                if markdown_exists:
                    document.status = "ready"
                else:
                    document.status = "conversion_failed"
                    document.conversion_error = "服务重启导致转换中断，请重试"

    logger.info("已恢复/标记中断的入库任务")
