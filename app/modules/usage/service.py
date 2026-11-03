"""用量统计服务: 台账聚合(费用按单价实时估算) + DeepSeek 余额查询(带短缓存)。"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from .models import LLMUsageLog

# 余额查询缓存: 5 分钟, 避免点一次面板打一次官方接口
_balance_cache: dict[str, Any] = {"at": 0.0, "data": None}
BALANCE_TTL_SECONDS = 300


class UsageService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def estimate_cost(prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> float:
        """估算费用(元): 缓存命中的输入按缓存单价, 其余按输入/输出单价。"""
        llm = settings.llm
        billable_input = max(prompt_tokens - cached_tokens, 0)
        cost = (
            billable_input * llm.price_input_per_1m
            + cached_tokens * llm.price_cached_per_1m
            + completion_tokens * llm.price_output_per_1m
        ) / 1_000_000
        return round(cost, 4)

    async def summary(self, days: int) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        row = (
            await self.session.execute(
                select(
                    func.count(LLMUsageLog.id),
                    func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.cached_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.duration_ms), 0),
                    func.coalesce(
                        func.sum(case((LLMUsageLog.status == "error", 1), else_=0)), 0
                    ),
                ).where(LLMUsageLog.created_at >= since)
            )
        ).one()
        calls, prompt, completion, cached, total_ms, errors = row
        calls = int(calls)
        return {
            "days": days,
            "calls": calls,
            "error_calls": int(errors),
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "cached_tokens": int(cached),
            "avg_duration_ms": int(total_ms) // calls if calls else 0,
            "estimated_cost": self.estimate_cost(int(prompt), int(completion), int(cached)),
        }

    async def daily(self, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            await self.session.execute(
                select(
                    func.date(LLMUsageLog.created_at).label("day"),
                    func.count(LLMUsageLog.id),
                    func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.cached_tokens), 0),
                    func.coalesce(
                        func.sum(case((LLMUsageLog.status == "error", 1), else_=0)), 0
                    ),
                )
                .where(LLMUsageLog.created_at >= since)
                .group_by(func.date(LLMUsageLog.created_at))
                .order_by(func.date(LLMUsageLog.created_at))
            )
        ).all()
        return [
            {
                "day": str(day),
                "calls": int(calls),
                "error_calls": int(errors),
                "prompt_tokens": int(prompt),
                "completion_tokens": int(completion),
                "cached_tokens": int(cached),
                "estimated_cost": self.estimate_cost(int(prompt), int(completion), int(cached)),
            }
            for day, calls, prompt, completion, cached, errors in rows
        ]

    async def by_scene(self, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            await self.session.execute(
                select(
                    LLMUsageLog.scene,
                    func.count(LLMUsageLog.id),
                    func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0),
                )
                .where(LLMUsageLog.created_at >= since)
                .group_by(LLMUsageLog.scene)
                .order_by(func.count(LLMUsageLog.id).desc())
            )
        ).all()
        return [
            {
                "scene": scene,
                "calls": int(calls),
                "prompt_tokens": int(prompt),
                "completion_tokens": int(completion),
            }
            for scene, calls, prompt, completion in rows
        ]

    async def quality(self, days: int) -> dict:
        """在线质量指标: 满意度/点踩归因(反馈表) + 错误率/耗时(用量台账)。"""
        from app.modules.feedback.models import AnswerFeedback

        since = datetime.now(timezone.utc) - timedelta(days=days)
        fb_rows = (
            await self.session.execute(
                select(
                    AnswerFeedback.rating,
                    func.count(AnswerFeedback.id),
                )
                .where(AnswerFeedback.created_at >= since)
                .group_by(AnswerFeedback.rating)
            )
        ).all()
        rating_map = {rating: int(cnt) for rating, cnt in fb_rows}
        up = rating_map.get("up", 0)
        down = rating_map.get("down", 0)
        total_fb = up + down

        category_rows = (
            await self.session.execute(
                select(AnswerFeedback.category, func.count(AnswerFeedback.id))
                .where(
                    AnswerFeedback.created_at >= since,
                    AnswerFeedback.category.is_not(None),
                )
                .group_by(AnswerFeedback.category)
                .order_by(func.count(AnswerFeedback.id).desc())
            )
        ).all()
        pending_down = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(AnswerFeedback).where(
                        AnswerFeedback.created_at >= since,
                        AnswerFeedback.rating == "down",
                        AnswerFeedback.status == "pending",
                    )
                )
            ).scalar_one()
        )

        usage_row = (
            await self.session.execute(
                select(
                    func.count(LLMUsageLog.id),
                    func.coalesce(
                        func.sum(case((LLMUsageLog.status == "error", 1), else_=0)), 0
                    ),
                    func.coalesce(func.sum(LLMUsageLog.duration_ms), 0),
                ).where(LLMUsageLog.created_at >= since)
            )
        ).one()
        calls, errors, total_ms = usage_row
        calls = int(calls)

        return {
            "days": days,
            "feedback_total": total_fb,
            "up": up,
            "down": down,
            "satisfaction_rate": round(up / total_fb, 4) if total_fb else None,
            "pending_down": pending_down,
            "feedback_by_category": [
                {"category": cat or "未归因", "count": int(cnt)}
                for cat, cnt in category_rows
            ],
            "calls": calls,
            "error_calls": int(errors),
            "error_rate": round(int(errors) / calls, 4) if calls else None,
            "avg_duration_ms": int(total_ms) // calls if calls else 0,
        }

    @staticmethod
    async def balance() -> dict:
        """代理官方余额接口(Get User Balance), 5 分钟缓存; 失败不抛错。"""
        now = time.monotonic()
        if _balance_cache["data"] is not None and now - _balance_cache["at"] < BALANCE_TTL_SECONDS:
            return _balance_cache["data"]
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    settings.llm.balance_url,
                    headers={"Authorization": f"Bearer {settings.llm.api_key}", "Accept": "application/json"},
                )
                resp.raise_for_status()
                payload = resp.json()
            balances = payload.get("balance_infos") or []
            main = balances[0] if balances else {}
            data = {
                "available": payload.get("is_available"),
                "currency": main.get("currency", ""),
                "total_balance": main.get("total_balance", "0"),
                "granted_balance": main.get("granted_balance", "0"),
                "topped_up_balance": main.get("topped_up_balance", "0"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            data = {"available": None, "message": "余额接口暂不可用(不影响记账)", "fetched_at": None}
        _balance_cache["at"] = now
        _balance_cache["data"] = data
        return data
