"""
知识库入库流水线（升级点2/3 重写）。

链路：读条款 markdown -> 结构感知切分（表格原子保护）-> 确定性 id + 内容指纹
     -> 比对指纹做增量入库（PG 父块表 + Milvus 向量，1:1）。

增量规则（以 PG 为真相源）：
- 指纹相同的块：PG、Milvus 都跳过，不重算向量；
- 新增/变化的块：PG upsert，Milvus upsert（重算向量）；
- 本次切分已不存在的旧块：两边都删。

不再使用 MinerU / 大模型改写：data/raw/md 下已是规整好的 markdown。
"""
import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Optional

from langchain_core.documents import Document
from langchain_milvus import Milvus

from app.core.config import APP_ROOT
from app.infra.database import AsyncSessionFactory
from .models import ParentChunk
from .repository import ParentChunkRepository
from .splitter import ChunkData, split_clause
from app.modules.product.repository import Product

# Milvus 标量字段里的章节路径分隔符（数组不被 langchain 字段类型推断支持）
PATH_SEP = " > "
VISIBILITY_PUBLIC = "public"
MILVUS_BATCH = 20


class IngestReport(dict):
    """单产品入库质检/增量统计（当作普通 dict 用即可）。"""


StageCallback = Optional[Callable[[str], Awaitable[None]]]


class RAGPipeline:
    def __init__(self, vector_store: Milvus):
        self._vector_store = vector_store

    async def product_info_to_store(
        self,
        product: Product,
        on_stage: StageCallback = None,
    ) -> IngestReport:
        """
        读产品对应条款 md，切分并增量入库到 PG 与 Milvus。
        :param on_stage: 可选异步回调, 用于后台任务更新阶段进度
        :return: 增量统计 {total, tables, added, changed, unchanged, deleted}
        """
        if not product.clause_name:
            raise ValueError("产品未绑定条款文件")

        clause_stem = Path(product.clause_name).stem
        markdown = self._read_clause_markdown(clause_stem)

        if on_stage is not None:
            await on_stage("splitting")
        chunks = split_clause(markdown, product_id=product.id, clause_stem=clause_stem)

        # 1) 以 PG 现有数据为基准，算出增量计划
        async with AsyncSessionFactory() as session:
            repository = ParentChunkRepository(session)
            existing = await repository.get_chunk_map(product.id)

        new_ids = {c.chunk_id for c in chunks}
        to_upsert: list[ChunkData] = []
        unchanged = 0
        for c in chunks:
            old_hash = existing.get(c.chunk_id)
            if old_hash is not None and old_hash == c.content_hash:
                unchanged += 1
            else:
                to_upsert.append(c)
        deleted_ids = [cid for cid in existing if cid not in new_ids]
        added = sum(1 for c in to_upsert if c.chunk_id not in existing)
        changed = len(to_upsert) - added

        # 2) PG：一个事务内 upsert 变化块 + 删除消失块
        if to_upsert or deleted_ids:
            if on_stage is not None:
                await on_stage("writing")
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    repository = ParentChunkRepository(session)
                    await repository.upsert_chunks(
                        [self._to_orm(c, product) for c in to_upsert]
                    )
                    await repository.delete_by_ids(deleted_ids)

        # 3) Milvus：新增/变化块写入（幂等），消失块删除；不变的块完全不碰
        # 注意：upsert 不会自动建 collection，空库首灌要先用 add_documents 触发建表
        # （按首批 metadata 推断字段类型），之后增量一律 upsert。
        if to_upsert:
            if on_stage is not None:
                await on_stage("embedding")
            docs = [self._to_document(c, product) for c in to_upsert]
            ids = [str(c.chunk_id) for c in to_upsert]
            # Milvus/Embedding 都是同步调用, 放进线程避免阻塞事件循环
            col_exists = await asyncio.to_thread(
                self._vector_store.client.has_collection,
                self._vector_store.collection_name,
            )
            for i in range(0, len(docs), MILVUS_BATCH):
                batch_docs = docs[i:i + MILVUS_BATCH]
                batch_ids = ids[i:i + MILVUS_BATCH]
                if not col_exists:
                    await asyncio.to_thread(
                        self._vector_store.add_documents,
                        batch_docs,
                        ids=batch_ids,
                    )
                    col_exists = True
                else:
                    await asyncio.to_thread(
                        self._vector_store.upsert,
                        ids=batch_ids,
                        documents=batch_docs,
                    )
        if deleted_ids:
            await asyncio.to_thread(
                self._vector_store.delete,
                ids=[str(x) for x in deleted_ids],
            )

        return IngestReport(
            product_id=product.id,
            product_name=product.name,
            clause_name=product.clause_name,
            total=len(chunks),
            tables=sum(1 for c in chunks if c.doc_type == "table"),
            added=added,
            changed=changed,
            unchanged=unchanged,
            deleted=len(deleted_ids),
        )

    def _read_clause_markdown(self, clause_stem: str) -> str:
        md_path = APP_ROOT / "data" / "raw" / "md" / f"{clause_stem}.md"
        return md_path.read_text(encoding="utf-8")

    @staticmethod
    def _to_orm(c: ChunkData, product: Product) -> ParentChunk:
        return ParentChunk(
            id=c.chunk_id,
            product_id=product.id,
            clause_name=product.clause_name,
            section_path=c.section_path,
            content=c.content,
            chunk_index=c.chunk_index,
            content_hash=c.content_hash,
            doc_type=c.doc_type,
            visibility=VISIBILITY_PUBLIC,
        )

    @staticmethod
    def _to_document(c: ChunkData, product: Product) -> Document:
        """
        一块 = 一个向量。Milvus 文本前拼章节路径（为表格/短定义补检索语境），
        纯内容仍以 PG 回表为准。所有标量字段每条都带，保证建 collection 时类型推断稳定。
        """
        path_text = PATH_SEP.join(c.section_path)
        page_text = f"{path_text}\n{c.content}" if path_text else c.content
        metadata = {
            "parent_id": str(c.chunk_id),
            "product_id": product.id,
            "clause_name": product.clause_name,
            "section_path": path_text,
            "chunk_index": c.chunk_index,
            "content_hash": c.content_hash,
            "doc_type": c.doc_type,
            "visibility": VISIBILITY_PUBLIC,
        }
        return Document(page_content=page_text, metadata=metadata)

    def close(self) -> None:
        """保留以兼容 app.rag 的关闭调用（新版无 MinerU 等外部客户端）。"""
        return None
