"""
    本模块是langchain在做持久化记忆存储
    用的数据库连接引擎初始化模块
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.logging import get_logger

# 导入打印日志的对象
logger = get_logger(__name__)

# 创建checkpointer专用连接池
checkpoint_pool = AsyncConnectionPool(
    conninfo=settings.db.checkpoint_url,
    min_size=1,  # 池最小连接数
    max_size=5,  # 池最大连接数
    kwargs={
        "autocommit": True,  # 自动提交事务
        "prepare_threshold": 0,  # 不做预准备sql
        "row_factory": dict_row,  # 查询结果以dict返回
    },
    open=False,  # 不自动创建连接
)

# 初始化方法,并返回会话连接对象
async def init_checkpointer() -> AsyncPostgresSaver:
    """初始化checkpointer"""

    # 1.初始化连接池
    await checkpoint_pool.open()  # 初始化连接
    await checkpoint_pool.wait()  # 等待连接池就绪

    # 2.创建checkpointer
    checkpointer = AsyncPostgresSaver(checkpoint_pool)

    # 启动checkpoint会话对象
    await checkpointer.setup()
    logger.info("Checkpointer初始化成功~✅️")

    # 返回会话对象
    return checkpointer


async def close_checkpointer() -> None:
    """关闭Checkpointer连接池"""
    await checkpoint_pool.close()
    logger.info("Checkpointer连接池已关闭")