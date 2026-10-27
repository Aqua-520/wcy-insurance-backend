"""
Milvus / Ollama 客户端工厂。

后台任务和清理操作使用独立客户端, 避免与聊天检索的全局 vector_store
共享同步连接, 也便于任务结束后及时释放。
"""
from langchain_milvus import BM25BuiltInFunction, Milvus
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings

COLLECTION_NAME = "insurance_collection"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
EMBEDDING_DIMENSIONS = 1024


def create_vector_store() -> Milvus:
    """创建一个新的 Milvus 客户端(调用方负责关闭)"""
    embeddings = OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        # 本地 Ollama 不能被系统代理接管, 否则请求会 502
        client_kwargs={"trust_env": False},
    )
    return Milvus(
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
        builtin_function=BM25BuiltInFunction(analyzer_params={"type": "chinese"}),
        vector_field=["dense", "sparse"],
        connection_args={"uri": settings.rag.milvus_url},
        drop_old=False,
        auto_id=False,
    )


def close_vector_store(vector_store: Milvus) -> None:
    """尽力关闭客户端, 不影响主流程"""
    try:
        vector_store.client.close()
    except Exception:
        pass
