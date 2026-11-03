# -*- coding: utf-8 -*-
"""
意图路由评测: 标注集跑 IntentRouter(正则+大模型), 输出准确率与错分清单。

指标: 意图分类准确率(会调 DeepSeek, 每题一次结构化输出)。
用法: cd agent-service && .venv/Scripts/python script/eval_intent.py
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.intent_router import intent_router  # noqa: E402

# (用户话术, 期望意图) 意图取值: recommendation_plan / claim / human_handoff / chit_chat
CASES = [
    # --- 咨询/推荐 ---
    ("帮我推荐一款适合3岁小孩的重疾险", "recommendation_plan"),
    ("30岁有医保预算3000元怎么配保险", "recommendation_plan"),
    ("这款产品的等待期是多久", "recommendation_plan"),
    ("医疗险和重疾险有什么区别", "recommendation_plan"),
    ("这款保险的免赔额是多少", "recommendation_plan"),
    ("投保年龄范围是什么", "recommendation_plan"),
    ("保费怎么交", "recommendation_plan"),
    ("帮我看看这个方案合不合适", "recommendation_plan"),
    ("我想给我妈买个医疗险", "recommendation_plan"),
    ("这个产品可以续保吗", "recommendation_plan"),
    # --- 理赔 ---
    ("我住院了怎么申请理赔", "claim"),
    ("理赔需要提交什么材料", "claim"),
    ("上次的理赔进度到哪了", "claim"),
    ("骨折了意外险能赔吗", "claim"),
    ("理赔款一般多久到账", "claim"),
    ("住院医疗能报销多少", "claim"),
    ("出险了第一步该做什么", "claim"),
    ("门诊手术可以理赔吗", "claim"),
    # --- 投诉/转人工 ---
    ("我要投诉你们的客服", "human_handoff"),
    ("转人工", "human_handoff"),
    ("我要找人工服务", "human_handoff"),
    ("为什么不处理我的投诉", "human_handoff"),
    ("这个问题一直没人解决,找你们领导", "human_handoff"),
    ("我要求人工处理", "human_handoff"),
    ("你们的服务太差了我要投诉", "human_handoff"),
    # --- 寒暄(正则前置) ---
    ("你好", "chit_chat"),
    ("您好", "chit_chat"),
    ("谢谢", "chit_chat"),
    ("谢谢你", "chit_chat"),
    ("再见", "chit_chat"),
    ("拜拜", "chit_chat"),
]


async def main() -> None:
    total = correct = 0
    misses: list[tuple[str, str, str]] = []
    per_class: dict[str, list[int]] = {}
    for text, expected in CASES:
        result = await intent_router.router(context="", user_question=text)
        got = result if isinstance(result, str) else result.intent
        # 寒暄的正则命中返回预制话术字符串, 统一记为 chit_chat
        if isinstance(result, str):
            got = "chit_chat"
        ok = got == expected
        total += 1
        correct += ok
        stat = per_class.setdefault(expected, [0, 0])
        stat[0] += 1
        stat[1] += ok
        if not ok:
            misses.append((text, expected, got))
        print(f"{'✅' if ok else '❌'} [{expected}] {text} → {got}")

    print(f"\n意图路由准确率: {correct}/{total} = {correct / total:.1%}")
    for cls, (t, c) in per_class.items():
        print(f"  {cls:<20} {c}/{t} = {c / t:.0%}")
    if misses:
        print("\n错分清单:")
        for text, expected, got in misses:
            print(f"  「{text}」 期望 {expected} → 实际 {got}")


if __name__ == "__main__":
    asyncio.run(main())
