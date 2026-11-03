"""用量上下文: 请求处理时写入 thread/user, 采集回调读取后随台账落库。"""
from contextvars import ContextVar
from typing import Any

current_usage_ctx: ContextVar[dict[str, Any]] = ContextVar("usage_ctx", default={})
