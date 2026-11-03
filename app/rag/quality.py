"""
入库质检: 切分质量统计 + 探针试搜。

质检卡点放在入库环节(七分资料三分搜索):
- split_quality_stats: 空块/超长/表格块/尺寸分布, 空块或超长 > 0 即不通过;
- probe_search: 入库后拿典型问题试检索, 有召回才算入库成功;
- 探针问题复用评测题集(data/eval/golden_questions.json)每产品前几条。
"""
from pathlib import Path
from typing import Any
import json

from .splitter import MAX_TEXT_CHARS, ChunkData

EVAL_QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "golden_questions.json"


def split_quality_stats(chunks: list[ChunkData]) -> dict[str, Any]:
    """切分质量统计; pass = 无空块且无超长文本块。"""
    lengths = [len(c.content) for c in chunks]
    empty = sum(1 for c in chunks if not c.content.strip())
    overlong = sum(1 for c in chunks if c.doc_type == "text" and len(c.content) > MAX_TEXT_CHARS)
    tables = sum(1 for c in chunks if c.doc_type == "table")
    return {
        "chunks": len(chunks),
        "tables": tables,
        "empty": empty,
        "overlong": overlong,
        "min_len": min(lengths) if lengths else 0,
        "max_len": max(lengths) if lengths else 0,
        "avg_len": (sum(lengths) // len(lengths)) if lengths else 0,
        "pass": empty == 0 and overlong == 0,
    }


def load_probe_questions(product_id: int, limit: int = 3) -> list[dict]:
    """从评测题集取该产品的前几条问题作入库探针; 文件缺失不阻塞入库。"""
    try:
        data = json.loads(EVAL_QUESTIONS_PATH.read_text(encoding="utf-8"))
        for entry in data.get("products", []):
            if entry.get("product_id") == product_id:
                return entry.get("questions", [])[:limit]
    except Exception:
        pass
    return []


async def probe_search(retriever, product_id: int, questions: list[dict], top_k: int = 3) -> list[dict]:
    """探针试搜: 每个问题检索一次, 记录召回数与是否命中期望关键词。"""
    results: list[dict] = []
    for item in questions:
        question = item.get("question", "")
        expected = item.get("expect", [])
        try:
            chunks = await retriever.retrieve(question=question, product_id=product_id, top_k=top_k)
            haystack = " > ".join(
                " > ".join(c.section_path) + " > " + c.content for c in chunks
            )
            hit = any(k in haystack for k in expected) if expected else len(chunks) > 0
            results.append({
                "question": question,
                "hits": len(chunks),
                "ok": bool(hit),
                "top_section": " > ".join(chunks[0].section_path) if chunks else None,
            })
        except Exception as exc:  # 探针失败不阻塞入库, 只记录
            results.append({"question": question, "hits": 0, "ok": False, "error": str(exc)[:120]})
    return results
