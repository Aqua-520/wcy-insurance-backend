"""
    在入口文件中实现对对象的初始化,还有向量数据库对象创建
"""
from langchain_milvus import Milvus, BM25BuiltInFunction
from langchain_ollama import OllamaEmbeddings
from .retriever import QuestionChunkRetriever
from app.core.config import settings
from .pipeline import RAGPipeline
from app.core.logging import get_logger

logger = get_logger(__name__)

# 初始化向量模型
ollama_embeddings = OllamaEmbeddings(model="qwen3-embedding:0.6b", dimensions=1024)

logger.info('ollama向量模型创建成功✅️')

# 初始化向量数据库
vector_store = Milvus(
    embedding_function=ollama_embeddings,  # 稠密向量模型
    collection_name="insurance_collection",  # collection名称
    builtin_function=BM25BuiltInFunction(  # 生成稀疏向量的函数
        analyzer_params={"type": "chinese"}  # 指定中文分词
    ),
    vector_field=["dense", "sparse"],  # 向量字段，包括稠密和稀疏
    connection_args={
        "uri": settings.rag.milvus_url,  # milvus的uri路径
    },
    drop_old=False,  # 是否删除旧的collection，避免重复创建
    # 自动主键
    auto_id=False
)

logger.info('向量数据库对象创建成功✅️')

# 初始化流水线对象
rag_pipeline = RAGPipeline(vector_store)
logger.info('流水线对象创建完毕✅️')

# 初始化检索对象
question_retriever = QuestionChunkRetriever(vector_store)
logger.info('向量匹配对象创建完毕创建成功✅️')

# 关闭向量数据库的函数
def close_vector_store():
    logger.info('关闭RAG资源.....')
    # 关闭向量数据库
    vector_store.client.close()
    # 关闭流水线对象中的mineru对象
    rag_pipeline.close()


# 暴露两个对象及一个关闭方法
__all__ = ['rag_pipeline','question_retriever','close_vector_store']



