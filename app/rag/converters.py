"""
PDF 条款转换: MinerU 解析 -> DeepSeek 清洗标题层级 -> 写入 Markdown。

清洗提示词与模型调用方式复用升级前的 app/rag/pipeline.py（见 git 历史）。
"""
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from langchain.chat_models import init_chat_model
from mineru import MinerU

from app.core.config import settings
from app.core.logging import get_logger

from .storage import atomic_write_text

logger = get_logger(__name__)

MARKDOWN_OPTIMIZATION_PROMPT = """
下面这份Markdown文档是从保险条款PDF解析得来，由于PDF中的各个小节是以表格形式存在，所以解析时出现错乱。你分析内容，帮我转为格式正确的Markdown，特别是标题编号要正确。
- 标题等级要从1级标题开始，逐层增加，目录和文档名不计入标题等级。
- 输出结果中不要包含正文开始之前的部分。
- 输出结果只包含Markdown正文，不要解释或代码围栏。
- 不要修改保险条款。
""".strip()

StageCallback = Optional[Callable[[str], Awaitable[None]]]

_model = None


class ConversionError(Exception):
    """PDF 解析或清洗失败"""


@dataclass
class ConversionResult:
    markdown_path: Path
    char_count: int
    duration_ms: int
    mineru_task_id: str | None = None


def _get_model():
    """惰性初始化 DeepSeek 客户端(单例)"""
    global _model
    if _model is None:
        _model = init_chat_model(
            settings.llm.chat_model,
            api_key=settings.llm.api_key,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=16000,
        )
    return _model


def _clean_markdown(raw: str) -> str:
    """调用大模型纠正标题层级, 并去掉可能的代码围栏"""
    response = _get_model().invoke(
        [
            {"role": "system", "content": MARKDOWN_OPTIMIZATION_PROMPT},
            {"role": "user", "content": raw},
        ]
    )
    text = (response.text or "").strip()
    if not text:
        raise ConversionError("大模型清洗结果为空")

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _mineru_extract(pdf_path: Path) -> tuple[str, str | None]:
    """同步调用 MinerU, 由 asyncio.to_thread 执行"""
    if not settings.rag.miner_u_token:
        raise ConversionError("未配置 MINERU_TOKEN，无法解析 PDF")

    client = MinerU(settings.rag.miner_u_token)
    try:
        # extract 的第一个参数必须是 str, 传 Path 会在 startswith 判断处报错
        result = client.extract(
            str(pdf_path),
            timeout=settings.storage.mineru_timeout_seconds,
        )
    finally:
        client.close()

    if result.state != "done":
        reason = result.error or result.err_code or result.state
        raise ConversionError(f"MinerU 解析失败: {reason}")
    if not result.markdown or not result.markdown.strip():
        raise ConversionError("MinerU 未返回 Markdown 内容")
    return result.markdown, result.task_id or None


async def convert_pdf_to_markdown(
    pdf_path: Path,
    md_path: Path,
    on_stage: StageCallback = None,
) -> ConversionResult:
    """
    把 PDF 转成规整 Markdown, 原子写入 md_path。

    :param on_stage: 可选异步回调, 用于更新任务阶段(converting / cleaning)
    """
    started = time.monotonic()

    if on_stage is not None:
        await on_stage("converting")
    raw_markdown, task_id = await asyncio.to_thread(_mineru_extract, pdf_path)

    if on_stage is not None:
        await on_stage("cleaning")
    markdown = await asyncio.to_thread(_clean_markdown, raw_markdown)

    if not markdown.strip():
        raise ConversionError("清洗后的 Markdown 为空")

    await asyncio.to_thread(atomic_write_text, md_path, markdown + "\n")

    return ConversionResult(
        markdown_path=md_path,
        char_count=len(markdown),
        duration_ms=int((time.monotonic() - started) * 1000),
        mineru_task_id=task_id,
    )
