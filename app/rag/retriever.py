"""
    此模块为根据用户问题进行语义相似度匹配的模块
"""
from langchain_milvus import Milvus
from pymilvus import Function, FunctionType
# 获取会话工厂
from app.infra.database import AsyncSessionFactory
from app.core.logging import get_logger
from .repository import ParentChunkRepository
from .models import ParentChunk

logger = get_logger(__name__)


# 定义自定义重排函数
def create_cross_encoder_ranker(queries: list[str]):
    return Function(
        # 重排函数名
        name="小汪重排ranker",
        input_field_names=["text"],  # 原始文档字段
        function_type=FunctionType.RERANK,  # ranker类型，这里是固定值
        params={
            # 使用模型进行reranker
            "reranker": "model",
            "provider": "ali",  # rerank模型提供者
            "model_name": "gte-rerank-v2",  # rerank模型名称
            "queries": queries,  # 查询条件
            "max_client_batch_size": 5,  # 向模型发送请求时的批处理限制
        },
    )

# 封装查询类
class QuestionChunkRetriever:
    def __init__(self,vector_store: Milvus):
        # 保存向量数据库对象
        self.vector_store = vector_store

    # 向量化匹配方法
    async def retrieve(self,question: str,product_id: int,top_k: int = 3) -> list[ParentChunk]:
        """
        用户输入问题进行向量化匹配
        :param question:
        :param product_id:
        :param top_k:
        :return:
        """
        # 使用向量数据库对象进行向量化匹配
        # 拿到匹配的子块结果列表
        child_chunks = self.vector_store.similarity_search(
            query=question,
            k=top_k,
            # 根据特定规则进行条件筛选,我们需要控制在某一个保险产品的范围内
            # 避免检索到别的保险产品内容
            expr=f'product_id == {product_id}',
            # 传入自定义排序函数
            reranker=create_cross_encoder_ranker([question])
        )

        # 对子块的父块id做去重,因为多个子块属于同一个父块id
        parent_ids = list(
            # 拿出每一个id做去重,转成字典,因为字典key有序并且唯一
            # 得到一个新字典,丢到list中再转回列表
            dict.fromkeys([
                str(child.metadata['parent_id'])
                for child in child_chunks
            ])
        )

        # 有了父块id后,从postgre数据库中进行id匹配,拿到父块chunk
        async with AsyncSessionFactory() as session:
            # 创建rag业务层检索对象
            rag_repository = ParentChunkRepository(session)

            # 调用查询方法
            parent_chunks_result = await rag_repository.find_by_parent_id(parent_ids)

        # 将数组变成字典
        parent_chunks_result_dict = {
            # 用父块的id绑定自身产品对象
            str(parent_chunk.id): parent_chunk
            for parent_chunk in parent_chunks_result
        }

        # 将列表根据parent_ids进行重新排序
        # 注意:Milvus中可能残留历史入库的子块,其parent_id指向的父块在重新入库时已被删除,
        # postgres中查不到,这类id直接跳过,否则KeyError会导致整个工具调用失败
        missing_ids = [pid for pid in parent_ids if pid not in parent_chunks_result_dict]
        if missing_ids:
            logger.warning(f"检索到{len(missing_ids)}个已失效的父块id(可能是重新入库后的残留向量),已跳过:{missing_ids}")

        result = [
            # 按照顺序通过id进行取值,查不到的死链直接跳过
            parent_chunks_result_dict[parent_id]
            for parent_id in parent_ids
            if parent_id in parent_chunks_result_dict
        ]

        # 返回最新的结果列表
        return result