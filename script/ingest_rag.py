"""
    实现对数据文档的向量化一件运行脚本
"""
import asyncio
import sys
from pathlib import Path

# 指定项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_milvus import BM25BuiltInFunction, Milvus
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings
from app.core.logging import get_logger
from app.infra.database import close_database, AsyncSessionFactory
from app.modules.product.models import Product
from app.modules.product.repository import ProductRepository
from app.rag.pipeline import RAGPipeline

logger = get_logger(__name__)


# 创建向量数据库的函数
def create_vector_store() -> Milvus:
    embeddings = OllamaEmbeddings(
        model="qwen3-embedding:0.6b",
        dimensions=1024,
    )
    return Milvus(
        embedding_function=embeddings,
        collection_name="insurance_collection",
        builtin_function=BM25BuiltInFunction(
            analyzer_params={"type": "chinese"}
        ),
        vector_field=["dense", "sparse"],
        connection_args={"uri": settings.rag.milvus_url},
        auto_id=True,
    )


# 获取全部的产品数据
async def get_all_insurance_product() -> list[Product]:
    # 创建数据库会话
    async with AsyncSessionFactory() as session:
        product_repository = ProductRepository(session)
        result = await product_repository.get_product_list_repository(None)

    return result


# 一键运行函数
async def main():
    # 获取向量数据库对象
    vector_store = create_vector_store()
    # 获取流水线对象
    pipeline = RAGPipeline(vector_store)

    # 获取产品数据
    all_product_list = await get_all_insurance_product()

    try:
        logger.info("开始构建RAG知识库", product_count=len(all_product_list))

        # 循环产品列表
        for index, product in enumerate(all_product_list, start=1):
            logger.info(
                "开始处理保险产品",
                progress=f"{index}/{len(all_product_list)}",
                product_id=product.id,
                product_name=product.name,
            )
            # 调用流水线方法
            await pipeline.product_info_to_store(product)

        logger.info('RAG知识库构建完毕✅️')
    except Exception as e:
        logger.error('知识库构建失败,错误原因: %s', str(e))
    finally:
        # 关闭流水线
        pipeline.close()
        # 关闭向量数据库
        vector_store.client.close()
        # 关闭postgre数据库
        await close_database()


if __name__ == "__main__":
    # 异步调用主函数
    asyncio.run(main())
