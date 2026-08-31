import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
import uvicorn
# 导入自定义全局异常处理类
from app.core.exceptions import ApplicationError

# 初始化日志系统
configure_logging(settings.logging.level)
logger = get_logger(__name__)

# 注入生命周期异步调用函数
# 生命周期管理（预留）
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"【{settings.app.name}】应用启动中...")
    from app.infra.database import check_database, close_database
    from app.infra.checkpoint import init_checkpointer, close_checkpointer
    from app.agents.insurance_advisor import init_insurance_agent
    try:
        # sqlalchemy框架初始化连接池
        await check_database()

        # 初始化langchain的连接池
        checkpointer = await init_checkpointer()

        # 初始化agent,将会话对象传入做记忆持久化
        # 绑定到app实例上,供业务层使用agent对象
        app.state.agent = init_insurance_agent(checkpointer)

        yield
    finally:
        logger.info("应用关闭中... ")

        # 关闭sqlalchemy的数据库连接池
        await close_database()

        # 关闭langchain的数据库连接池
        await close_checkpointer()

app = FastAPI(
    # 从环境变量读取项目名称和是否开启debug
    title=settings.app.name,
    debug=settings.app.debug,
    lifespan=lifespan
)
# 导入每个模块的路由对象进行挂载
from app.modules.product.router import router as product_router
app.include_router(product_router)
# 导入会话管理路由
from app.modules.chat_thread.router import router as chat_thread_router
app.include_router(chat_thread_router)
# 导入大模型消息调用的路由
from app.modules.chat.router import router as chat_router
app.include_router(chat_router)

# CORS配置，解决跨域问题
# 放行5173端口的访问,让浏览器忽略跨域问题
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理函数
@app.exception_handler(ApplicationError)
async def handle_exception_error(request:Request ,exc: ApplicationError)-> JSONResponse:
    # 直接返回响应状态码
    return JSONResponse(
        # 绑定自定义异常对象身上的code
        status_code=exc.status_code,
        # 绑定自定义异常身上的自定义消息
        content={
            "code": exc.code,
            "message": exc.message
        }
    )



@app.get("/health", summary="健康检测接口")
async def health_check() -> dict[str, str]:
    logger.info("执行健康检查")
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=False,
        loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    )