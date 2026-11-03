# -*- coding: utf-8 -*-
"""
检索质量评测: golden_questions.json 逐题跑 retriever, 输出命中率与延迟报告。

指标: 检索命中率@3(期望关键词出现在 top-k 的章节路径或正文)、平均/p95 检索延迟。
用法: cd agent-service && .venv/Scripts/python script/eval_retrieval.py
依赖: Milvus + Ollama 已启动、知识库已入库。
"""
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag import question_retriever  # noqa: E402 拉起 Milvus/Ollama 单例

TOP_K = 3


def is_hit(chunks, expect: list[str]) -> bool:
    if not chunks:
        return False
    hay = " > ".join(" > ".join(c.section_path) + " > " + c.content for c in chunks)
    return any(k in hay for k in expect) if expect else True


async def main() -> None:
    data = json.loads(
        (ROOT / "data" / "eval" / "golden_questions.json").read_text(encoding="utf-8")
    )
    lines = [
        f"# 检索质量评测报告 {date.today().isoformat()}",
        "",
        f"- 评测集: {sum(len(p['questions']) for p in data['products'])} 题 / {len(data['products'])} 产品",
        f"- top_k = {TOP_K}, 命中判定 = 期望关键词出现在 top-k 章节路径或正文",
        "",
    ]
    total = hits = 0
    latencies: list[float] = []
    topic_stat: dict[str, list[int]] = {}

    for product in data["products"]:
        p_total = p_hits = 0
        rows = []
        for q in product["questions"]:
            t0 = time.monotonic()
            chunks = await question_retriever.retrieve(
                question=q["question"], product_id=product["product_id"], top_k=TOP_K
            )
            latencies.append(time.monotonic() - t0)
            ok = is_hit(chunks, q["expect"])
            p_total += 1
            total += 1
            p_hits += ok
            hits += ok
            stat = topic_stat.setdefault(q["topic"], [0, 0])
            stat[0] += 1
            stat[1] += ok
            top1 = " > ".join(chunks[0].section_path) if chunks else "(无召回)"
            rows.append(f"- {'✅' if ok else '❌'} [{q['topic']}] {q['question']} → top1: {top1}")
        lines.append(f"## {product['product_name']} — {p_hits}/{p_total}")
        lines.extend(rows)
        lines.append("")

    latencies.sort()
    avg_ms = sum(latencies) / len(latencies) * 1000 if latencies else 0
    p95_ms = latencies[int(len(latencies) * 0.95) - 1] * 1000 if latencies else 0
    overall = hits / total if total else 0

    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- **检索命中率@{TOP_K}: {hits}/{total} = {overall:.1%}**")
    lines.append(f"- 平均检索延迟: {avg_ms:.0f} ms; P95: {p95_ms:.0f} ms")
    lines.append("")
    lines.append("| 主题 | 题数 | 命中 | 命中率 |")
    lines.append("|---|---|---|---|")
    for topic, (t, h) in sorted(topic_stat.items(), key=lambda kv: kv[1][1] / kv[1][0]):
        lines.append(f"| {topic} | {t} | {h} | {h / t:.0%} |")

    report_path = ROOT / "data" / "eval" / f"report_retrieval_{date.today().isoformat()}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"检索命中率@{TOP_K}: {hits}/{total} = {overall:.1%}")
    print(f"平均延迟 {avg_ms:.0f} ms / P95 {p95_ms:.0f} ms")
    print("按主题(升序=薄弱环节):")
    for topic, (t, h) in sorted(topic_stat.items(), key=lambda kv: kv[1][1] / kv[1][0]):
        print(f"  {topic:<8} {h}/{t} = {h / t:.0%}")
    print(f"完整报告: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
