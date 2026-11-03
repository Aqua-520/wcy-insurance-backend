"""
LangChain 用量采集回调。

挂在各场景的 ChatModel 上(见 agents/*/init), on_llm_end 把 token 用量写入台账。
铁律: 采集失败只记日志, 绝不影响对话主流程。
"""
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.logging import get_logger
from app.infra.database import AsyncSessionFactory

from .context import current_usage_ctx
from .models import LLMUsageLog

logger = get_logger(__name__)


def _extract_usage(response: LLMResult) -> dict[str, Any]:
    """从 LLMResult 里尽力抠出 token 用量(不同模型/流式形态位置不同)。"""
    usage: dict[str, Any] = {}
    llm_output = response.llm_output or {}
    # 1) 非流式常见: llm_output.token_usage
    if isinstance(llm_output.get("token_usage"), dict):
        usage = llm_output["token_usage"]
    # 2) 流式聚合常见: 末条消息的 usage_metadata
    if not usage and response.generations and response.generations[0]:
        message = getattr(response.generations[0][-1], "message", None)
        meta = getattr(message, "usage_metadata", None) if message is not None else None
        if meta:
            usage = {
                "prompt_tokens": meta.get("input_tokens", 0),
                "completion_tokens": meta.get("output_tokens", 0),
            }
        if not usage and message is not None:
            usage = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    cached = int(
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cached_tokens")
        or details.get("cached_tokens")
        or 0
    )
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        "cached_tokens": cached,
        "model": llm_output.get("model_name") or "",
    }


class UsageCollector(AsyncCallbackHandler):
    """按场景记录一次 LLM 调用的用量与耗时。"""

    def __init__(self, scene: str):
        self.scene = scene
        self._started: dict[UUID, float] = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._started[run_id] = time.monotonic()

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._started.setdefault(run_id, time.monotonic())

    async def on_llm_end(self, response: LLMResult, *, run_id, **kwargs):
        try:
            info = _extract_usage(response)
            started = self._started.pop(run_id, None)
            duration_ms = int((time.monotonic() - started) * 1000) if started else None
            ctx = current_usage_ctx.get()
            async with AsyncSessionFactory() as session:
                session.add(
                    LLMUsageLog(
                        scene=self.scene,
                        thread_id=ctx.get("thread_id"),
                        user_id=ctx.get("user_id"),
                        model=info["model"] or ctx.get("model") or "",
                        prompt_tokens=info["prompt_tokens"],
                        completion_tokens=info["completion_tokens"],
                        cached_tokens=info["cached_tokens"],
                        duration_ms=duration_ms,
                        status="ok",
                    )
                )
                await session.commit()
        except Exception:
            logger.debug("用量采集落库失败", exc_info=True)

    async def on_llm_error(self, error: BaseException, *, run_id, **kwargs):
        try:
            started = self._started.pop(run_id, None)
            duration_ms = int((time.monotonic() - started) * 1000) if started else None
            ctx = current_usage_ctx.get()
            async with AsyncSessionFactory() as session:
                session.add(
                    LLMUsageLog(
                        scene=self.scene,
                        thread_id=ctx.get("thread_id"),
                        user_id=ctx.get("user_id"),
                        model=ctx.get("model") or "",
                        duration_ms=duration_ms,
                        status="error",
                    )
                )
                await session.commit()
        except Exception:
            logger.debug("用量采集(错误态)落库失败", exc_info=True)


def usage_collector(scene: str) -> UsageCollector:
    return UsageCollector(scene)
