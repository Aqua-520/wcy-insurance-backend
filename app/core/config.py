import os
from pathlib import Path

from pydantic import Field, computed_field, model_validator, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

# 以当前文件为基准，找向上2级的父目录，也就是项目的根目录
APP_ROOT = Path(__file__).resolve().parents[2]

# 当前运行环境: dev(默认,本地开发) / prod(生产)
# 该开关必须来自操作系统环境变量(如 docker -e APP_ENV=prod),
# 不能写进 .env 文件——要先知道环境才能决定加载哪个 env 文件。
APP_ENV = os.environ.get("APP_ENV", "dev").lower()

# 环境白名单提前校验: 拼错(如 test/production)立刻给出清晰错误,
# 而不是等加载一个不存在的 .env.xxx 时报一堆"缺少必填项"
if APP_ENV not in ("dev", "prod"):
    raise ValueError(f"不支持的 APP_ENV={APP_ENV!r}，只允许 dev / prod")

# 按环境加载对应的配置文件: .env.dev / .env.prod
# 真实值文件不进 git, 仓库只提供 .env.*.example 模板
ENV_FILE = APP_ROOT / f".env.{APP_ENV}"

class EnvSettings(BaseSettings):
    """公共settings，配置.env文件位置"""
    model_config = SettingsConfigDict(
        env_file=(ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",  # settings中未定义的字段被忽略
    )

class AppSettings(EnvSettings):
    """应用相关设置"""
    name: str = Field(alias="APP_NAME")
    host: str = Field(alias="APP_HOST", default="127.0.0.1")
    port: int = Field(alias="APP_PORT", default=8001)
    debug: bool = Field(alias="APP_DEBUG", default=True, description="是否开启FastAPI的DEBUG模式")

class DatabaseSettings(EnvSettings):
    """数据库相关设置"""
    host: str = Field(alias="DB_HOST", default="localhost")
    port: int = Field(alias="DB_PORT", default=5432)
    name: str = Field(alias="DB_NAME", default="insurance")
    user: str = Field(alias="DB_USER", default="insurance")
    password: str = Field(alias="DB_PASSWORD", default="insurance123")
    echo: bool = Field(alias="DB_ECHO",default=False)
    pool_size: int = Field(alias="DB_POOL_SIZE", default=5)
    max_overflow: int = Field(alias="DB_MAX_OVERFLOW", default=10)
    pool_timeout: int = Field(alias="DB_POOL_TIMEOUT", default=30)
    pool_recycle: int = Field(alias="DB_POOL_RECYCLE", default=1800)

    # 数据库连接引擎的连接地址
    def base_url(self, scheme) -> str:
        # 自动拼接URL路径
        return PostgresDsn.build(
            scheme=scheme,
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password
        ).encoded_string()

    @computed_field
    @property
    def url(self) -> str:
        # 根据情况返回不同的数据库连接地址
        return self.base_url("postgresql+asyncpg")

    # langchain使用的postgre地址
    @computed_field
    @property
    def checkpoint_url(self) -> str:
        return self.base_url('postgresql')

class LLMSettings(EnvSettings):
    """模型相关配置"""
    api_key: str = Field(alias="DEEPSEEK_API_KEY")
    chat_model: str = Field(alias="CHAT_MODEL", default="deepseek-v4-flash")

class LoggingSettings(EnvSettings):
    """日志相关配置"""
    level: str = Field(alias="LOGGING_LEVEL", default="INFO") # 可选值：DEBUG、INFO、WARNING、ERROR、CRITICAL

# 认证鉴权相关环境变量配置
class AuthSettings(EnvSettings):
    # JWT 签名密钥(生产环境必须通过环境变量覆盖)
    secret_key: str = Field(alias="JWT_SECRET", default="anxinbao-dev-secret-please-change")
    # 签名算法
    algorithm: str = Field(alias="JWT_ALGORITHM", default="HS256")
    # access_token 有效期(分钟),默认 24 小时
    access_token_expire_minutes: int = Field(alias="JWT_EXPIRE_MINUTES", default=1440)

# rag相关环境变量配置
class RagSettings(EnvSettings):
    miner_u_token: str = Field(alias="MINERU_TOKEN")
    # 向量数据库配置
    milvus_host: str = Field(alias="MILVUS_HOST")
    milvus_port: int = Field(alias="MILVUS_PORT", default=19530)

    # 计算属性:链接地址
    @computed_field
    @property
    def milvus_url(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"


# 后台管理员初始账号配置(仅种子脚本使用)
class AdminSettings(EnvSettings):
    init_username: str = Field(alias="ADMIN_INIT_USERNAME", default="admin")
    init_password: str = Field(alias="ADMIN_INIT_PASSWORD", default="admin123456")
    init_display_name: str = Field(alias="ADMIN_INIT_DISPLAY_NAME", default="系统管理员")

DEFAULT_ADMIN_PASSWORD = "admin123456"


# 知识库上传文件存储配置
class StorageSettings(EnvSettings):
    kb_root: str = Field(alias="KB_STORAGE_ROOT", default="data")
    max_upload_mb: int = Field(alias="KB_MAX_UPLOAD_MB", default=50)
    mineru_timeout_seconds: int = Field(alias="MINERU_TIMEOUT_SECONDS", default=300)

    @property
    def root_path(self) -> Path:
        """存储根目录(默认 agent-service/data)"""
        return APP_ROOT / self.kb_root

    @property
    def md_dir(self) -> Path:
        """流水线唯一读取的 Markdown 目录"""
        return self.root_path / "raw" / "md"

    @property
    def pdf_dir(self) -> Path:
        """原始 PDF 存放目录"""
        return self.root_path / "raw" / "kb"

    @property
    def tmp_dir(self) -> Path:
        """上传临时文件目录"""
        return self.root_path / "tmp"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

class Settings(BaseSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    # 认证鉴权配置
    auth: AuthSettings = Field(default_factory=AuthSettings)
    # 新增环境变量挂载
    rag: RagSettings = Field(default_factory=RagSettings)
    # 后台管理员与上传存储配置
    admin: AdminSettings = Field(default_factory=AdminSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    # 当前环境标识(dev/prod), 方便日志与排查
    env: str = APP_ENV

    @model_validator(mode="after")
    def _check_env_safety(self) -> "Settings":
        if APP_ENV == "prod":
            # 生产环境必须关闭 debug
            if self.app.debug:
                raise ValueError("生产环境(APP_ENV=prod)必须设置 APP_DEBUG=false")
            # 生产环境必须通过环境变量注入真实 JWT 密钥, 禁止使用内置默认值
            if self.auth.secret_key == "anxinbao-dev-secret-please-change":
                raise ValueError(
                    "生产环境(APP_ENV=prod)检测到 JWT_SECRET 仍为开发默认值，"
                    "请通过环境变量注入一个随机强密钥"
                )
            # 生产环境必须覆盖管理员默认密码
            if self.admin.init_password == DEFAULT_ADMIN_PASSWORD:
                raise ValueError(
                    "生产环境(APP_ENV=prod)检测到 ADMIN_INIT_PASSWORD 仍为开发默认值，"
                    "请通过环境变量注入强密码"
                )
            # 上传目录必须是绝对安全配置? 这里仅校验大小上限合理
            if self.storage.max_upload_mb <= 0:
                raise ValueError("KB_MAX_UPLOAD_MB 必须大于 0")
        return self

# 项目启动直接初始化
settings = Settings()