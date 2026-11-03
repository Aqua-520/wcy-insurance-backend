"""
工作台(数据首页)服务: 内部员工登录后的待办概览。

按岗位过滤数据范围: cs 看工单/投保意向, kb 看知识库/反馈/用量, admin 看全部。
只做聚合计数, 不做业务逻辑; 每个数字都对应一个可点击进入的管理面板。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.feedback.models import AnswerFeedback
from app.modules.intent.models import ApplicationIntent, Policy
from app.modules.kb.models import IngestionJob, KbDocument
from app.modules.ticket.models import Ticket
from app.modules.usage.models import LLMUsageLog


class DashboardService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _ticket_counts(self) -> dict:
        rows = (
            await self.session.execute(
                select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
            )
        ).all()
        by_status = {status: int(cnt) for status, cnt in rows}
        today = datetime.now(timezone.utc) - timedelta(hours=24)
        today_new = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(Ticket).where(Ticket.created_at >= today)
                )
            ).scalar_one()
        )
        return {
            "pending": by_status.get("pending", 0),
            "reopened": by_status.get("reopened", 0),
            "processing": by_status.get("processing", 0),
            "closed": by_status.get("closed", 0),
            "today_new": today_new,
        }

    async def _intent_counts(self) -> dict:
        rows = (
            await self.session.execute(
                select(ApplicationIntent.status, func.count(ApplicationIntent.id))
                .group_by(ApplicationIntent.status)
            )
        ).all()
        by_status = {status: int(cnt) for status, cnt in rows}
        now = datetime.now(timezone.utc)
        # SLA 超时: 在途且 (过下次跟进时间 或 24h 无任何跟进)
        overdue = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(ApplicationIntent).where(
                        ApplicationIntent.status.in_(("pending", "contacted")),
                        (
                            (ApplicationIntent.next_follow_at < now)
                            | (
                                (ApplicationIntent.next_follow_at.is_(None))
                                & (ApplicationIntent.follow_count == 0)
                                & (ApplicationIntent.created_at < now - timedelta(hours=24))
                            )
                        ),
                    )
                )
            ).scalar_one()
        )
        # 结果标签分布(战败原因等)
        result_rows = (
            await self.session.execute(
                select(ApplicationIntent.last_result, func.count(ApplicationIntent.id))
                .where(ApplicationIntent.last_result.is_not(None))
                .group_by(ApplicationIntent.last_result)
            )
        ).all()
        # 平均成交周期(天)
        avg_days = await self.session.scalar(
            select(
                func.avg(
                    func.extract("epoch", ApplicationIntent.updated_at - ApplicationIntent.created_at)
                    / 86400
                )
            ).where(ApplicationIntent.status == "converted")
        )
        total = sum(by_status.values())
        converted = by_status.get("converted", 0)
        return {
            "pending": by_status.get("pending", 0),
            "contacted": by_status.get("contacted", 0),
            "converted": converted,
            "closed": by_status.get("closed", 0),
            "overdue": overdue,
            "conversion_rate": round(converted / total, 4) if total else None,
            "avg_convert_days": round(float(avg_days), 1) if avg_days is not None else None,
            "result_distribution": [
                {"result": result or "未标注", "count": int(cnt)}
                for result, cnt in result_rows
            ],
        }

    async def _care_counts(self) -> dict:
        """成交后延伸提醒: 近7天成交建议回访 + 30天内到期续期提醒"""
        now = datetime.now(timezone.utc)
        recent_converted = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(ApplicationIntent).where(
                        ApplicationIntent.status == "converted",
                        ApplicationIntent.updated_at >= now - timedelta(days=7),
                    )
                )
            ).scalar_one()
        )
        expiring = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(Policy).where(
                        Policy.status == "active",
                        Policy.expires_at.is_not(None),
                        Policy.expires_at <= now + timedelta(days=30),
                        Policy.expires_at >= now,
                    )
                )
            ).scalar_one()
        )
        return {"recent_converted": recent_converted, "expiring_30d": expiring}

    async def _feedback_counts(self) -> dict:
        pending_down = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(AnswerFeedback).where(
                        AnswerFeedback.rating == "down",
                        AnswerFeedback.status == "pending",
                    )
                )
            ).scalar_one()
        )
        return {"pending_down": pending_down}

    async def _kb_counts(self) -> dict:
        jobs_active = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(IngestionJob).where(
                        IngestionJob.status.in_(("pending", "processing"))
                    )
                )
            ).scalar_one()
        )
        since = datetime.now(timezone.utc) - timedelta(hours=48)
        jobs_failed = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(IngestionJob).where(
                        IngestionJob.status == "failed",
                        IngestionJob.created_at >= since,
                    )
                )
            ).scalar_one()
        )
        docs_failed = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(KbDocument).where(
                        KbDocument.status == "conversion_failed"
                    )
                )
            ).scalar_one()
        )
        return {"jobs_active": jobs_active, "jobs_failed": jobs_failed, "docs_failed": docs_failed}

    async def _usage_counts(self) -> dict:
        today = datetime.now(timezone.utc) - timedelta(hours=24)
        calls_today = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(LLMUsageLog).where(
                        LLMUsageLog.created_at >= today
                    )
                )
            ).scalar_one()
        )
        since = datetime.now(timezone.utc) - timedelta(days=7)
        calls, errors = (
            await self.session.execute(
                select(
                    func.count(LLMUsageLog.id),
                    func.coalesce(
                        func.sum(case((LLMUsageLog.status == "error", 1), else_=0)),
                        0,
                    ),
                ).where(LLMUsageLog.created_at >= since)
            )
        ).one()
        return {
            "calls_today": calls_today,
            "error_rate_7d": round(int(errors) / int(calls), 4) if calls else None,
        }

    async def overview(self, role: str) -> dict:
        """按岗位组装工作台数据; 非 admin 只返回其岗位对应的板块。"""
        data: dict = {"role": role}
        if role in ("admin", "cs"):
            data["tickets"] = await self._ticket_counts()
            data["intents"] = await self._intent_counts()
            data["care"] = await self._care_counts()
        if role in ("admin", "kb"):
            data["feedbacks"] = await self._feedback_counts()
            data["kb"] = await self._kb_counts()
            data["usage"] = await self._usage_counts()
        return data
