"""
    整合的流水线类
    1,提供对文档进行转换成markdown
    2,对markdown文本通过大模型重新整合
    3,对markdown文本进行切片
    4,切片chunk文本,转换成postgre数据库对象
    5,每个markdown父切片进行二次切片,构建Document对象,存入子块列表
    6,存入普通数据库和向量数据库的方法
"""
from uuid import uuid4

from langchain_core.documents import Document
from langchain_milvus import Milvus
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain.chat_models import init_chat_model
from mineru import MinerU
# 导入项目根目录
from app.core.config import APP_ROOT
# 导入环境变量配置对象
from app.core.config import settings
# 导入数据库表映射对象
from .models import ParentChunk
# 导入工厂函数创建session
from app.infra.database import AsyncSessionFactory
# 导入数据层操作类
from .repository import ParentChunkRepository
from app.modules.product.repository import Product

# 大模型优化限定系统提示词
MARKDOWN_OPTIMIZATION_PROMPT = """
下面这份Markdown文档是从保险条款PDF解析得来，由于PDF中的各个小节是以表格形式存在，所以解析时出现错乱。你分析内容，帮我转为格式正确的Markdown，特别是标题编号要正确。
- 标题等级要从1级标题开始，逐层增加，目录和文档名不计入标题等级。
- 输出结果中不要包含正文开始之前的部分。
- 输出结果只包含Markdown正文，不要解释或代码围栏。
- 不要修改保险条款。
""".strip()


class RAGPipeline:
    def __init__(self,vector_store: Milvus):
        # 创建mineru客户端
        self._mineru_client = MinerU(settings.rag.miner_u_token)
        # 创建聊天大模型对象
        self._deepseek = init_chat_model(
            "deepseek-v4-flash",
            api_key=settings.llm.api_key,
            extra_body={'thinking': {'type': 'disabled'}},
            max_tokens=200000
        )
        # markdown切分器
        self._markdown_splitter = MarkdownHeaderTextSplitter(
            # 按照标题拆分四级
             headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
                ("####", "h4"),
            ],
            strip_headers=True,  # 去除标题头部(后期需要手动将多级标题拼接到正文内容中)
        )
        # 子块的递归切分器
        self._child_splitter = RecursiveCharacterTextSplitter(
            # 定义切分规则
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "；", ";", "，", ","],
            keep_separator="end",
        )
        # 外界初始化完传入向量数据库对象
        self._vector_store = vector_store

    # 整合调用的启动函数
    async def product_info_to_store(self,product: Product):
        """
        整合函数,传入文本对象,自动调用各种方法完成pdf条款文档的数据库保存
        自动根据产品对象的字段,去检索到对应的文件路径
        :param product: 保险产品对象
        :return: 无
        """
        # 自动检索对应文档,进行切片
        markdown_response = await self._parse_and_optimize_md(product.clause_name)
        # 将文档丢入切片函数完成切片
        parent_chunks, child_chunks = await self._chunks(markdown_response,product_id=product.id,clause_name=product.clause_name)
        # 将两个切片完成数据库保存操作
        await self._save_parent_chunks(product.id,parent_chunks)
        await self._save_child_chunks(product.id,child_chunks)



    # 通过mineru对文档进行转换的markdown函数
    async def _parse_and_optimize(self,clause_name: str) -> str:
        """
        接收一个检索出来的文档名称,打开pdf文件,去做转换和优化
        :param clause_name: 需要被处理的文档名称
        :return: 吐出被聊天大模型优化过后的markdown文件
        """
        # 解析文件资源路径
        file_path = APP_ROOT / 'data' / 'raw' / 'kb' / clause_name

        # 将文件路径丢给mineru,直接进行文件解析得到转换后的结果
        mineru_result =  self._mineru_client.extract(file_path)

        # 将mineru解析过的结果用大模型做优化,避免标题层级出现问题
        markdown_response = self._deepseek.invoke(
            [
                {"role": "system", "content": MARKDOWN_OPTIMIZATION_PROMPT},
                # 将mineru转出来的对象,里面的markdown文本喂给大模型
                {"role": "user", "content": mineru_result.markdown},
            ]
        )

        # 返回大模型优化过后的文本
        return markdown_response.text

    async def _parse_and_optimize_md(self,clause_name: str) -> str:
        """
        接收一个检索出来的文档名称,打开pdf文件,去做转换和优化
        本函数直接吐出磊哥给的转换好的md文档
        :param clause_name: 需要被处理的文档名称
        :return: md文档读取结果
        """
        # 解析文件资源路径
        file_path = APP_ROOT / 'data' / 'raw' / 'md' / clause_name

        md_path = file_path.with_suffix('.md')  # 自动替换后缀

        # 打开文件
        with open(md_path,'r',encoding='utf-8') as file:
            markdown_text = file.read()

        # 返回大模型优化过后的文本
        return markdown_text

    # 把上面函数的文本拿来做切片处理,返回两个切分好的文本列表
    async def _chunks(self,markdown_text: str,product_id: int,clause_name: str) -> tuple[list[ParentChunk],list[Document]]:
        """
        将大模型处理好的markdown文本进行切片
        先按段落切成父块,然后创建sql对象,将父块数据整理后写入
        再按照父块做二次拆分,将每个父块切成几个子块,子块对象的数据进行指定规则整理后存入列表
        :param markdown_text: 大模型处理好的文本
        :return: 返回元组,存储切片好的两个切片列表
        """

        # 定义转换后的结果集列表,后期将父块批量添加入postgresql
        parent_chunks: list[ParentChunk] = []
        # 子块结果列表,创建document对象,存入向量数据库
        child_chunks: list[Document] = []

        # 做markdown文本切分
        sections = self._markdown_splitter.split_text(markdown_text)

        # 循环拆分出来的对象,做数据转换
        for section in sections:
            # 每一个section是document对象,也就是父块的原数据来源

            # 创建表对象
            # section_path指的就是从根标题找到文章正文的路径
            section_path = section.metadata.values()
            parent_chunk = ParentChunk(
                id=uuid4(),
                product_id=product_id,
                clause_name=clause_name,
                section_path=section_path,
                content=section.page_content
            )
            # 将单个表对象存入列表,后续做批量新增
            parent_chunks.append(parent_chunk)

            # 接下来对子块做切分
            # 传入切分好的父块doc对象
            section_child_chunks = self._child_splitter.split_documents([section])
            for child_chunk in section_child_chunks:
                # 修改子chunk的对象属性
                child_chunk.metadata = {
                    # 关联父块id
                    'parent_id': str(parent_chunk.id),
                    'product_id': product_id  # 关联产品id
                }
                # 修复每一个子块的所属,也就是它的标题
                child_chunk.page_content = '\n'.join(section_path) + '\n' + child_chunk.page_content
            # 循环结束后,将每一个子chunk添加进列表中
            child_chunks.extend(section_child_chunks)

        # 返回结果元组
        return parent_chunks,child_chunks

    # 父块存储方法
    async def _save_parent_chunks(self,product_id: int,parent_chunks: list[ParentChunk]) -> None:
        """
        先删除旧的切片数据,然后新增最新的
        :param product_id: 产品id
        :param parent_chunks: 切片好的产品对象
        :return: 无返回值
        """
        async with AsyncSessionFactory() as session:
            async with session.begin():
                #  创建业务层操作对象
                repository = ParentChunkRepository(session)

                # 根据产品id删除切片
                await repository.delete_parent_chunks(product_id)

                # 批量保存最新的保险产品条款切片
                await repository.add_parent_chunks(parent_chunks)

    # 子块的存储方法
    async def _save_child_chunks(self,product_id: int,child_chunks: list[Document]):
        """
        子块接收拆分好的子块列表,分批次存入向量数据库
        :param product_id: 保险产品id,用于删除该产品的旧子块向量
        :param child_chunks: 切片好的子块Document列表
        :return:
        """
        # 与父块的处理保持一致:先删除该产品的旧子块向量再写入。
        # 否则重新入库后旧子块会残留在Milvus中,其parent_id指向已被删除的父块,
        # 检索时这些死链会稀释结果甚至导致工具报错
        self._vector_store.delete(expr=f"product_id == {product_id}")

        # 做20个一批的写入操作
        batch_documents = [
            child_chunks[i:i + 20]
            for i in range(0, len(child_chunks), 20)
        ]
        # 写入操作
        for batch in batch_documents:
            # 使用向量数据库添加方法,循环按20个一组进行数据库写入操作
            self._vector_store.add_documents(batch)

    def close(self):
        """
        流水线结束后释放一些连接资源,避免占用内存
        :return:
        """
        self._mineru_client.close()