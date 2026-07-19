"""ProactiveLoop: APScheduler wiring for heartbeat + builtin/custom jobs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from fae.llm.types import ChatMessage, ChatRequest, LLMConfig
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.heartbeat import HeartbeatLoop
from fae.scheduler.jobs import builtin_job_specs
from fae.scheduler.proactive import OutreachPolicy
from fae.scheduler.store import ScheduleStore, StoredJob

if TYPE_CHECKING:
    from fae.agent.skills_runtime import SkillRuntime
    from fae.llm.client import LLMClient
    from fae.memory.consolidation import SleeptimeScheduler
    from fae.memory.episodic import EpisodicStore
    from fae.memory.recall_store import RecallStore
    from fae.scheduler.activity import ActivityTracker

logger = logging.getLogger("fae.scheduler.loop")


class ProactiveLoop:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        activity: ActivityTracker,
        delivery: NotificationDelivery,
        skills: SkillRuntime | None = None,
        llm: LLMClient | None = None,
        episodic: EpisodicStore | None = None,
        recall: RecallStore | None = None,
        sleeptime: SleeptimeScheduler | None = None,
        heartbeat_seconds: float = 30.0,
        outreach_idle_hours: float = 6.0,
        outreach_cooldown_hours: float = 12.0,
        outreach_max_per_day: int = 1,
        default_llm_config: LLMConfig | None = None,
        timezone: str = "local",
    ) -> None:
        self.store = store
        self.activity = activity
        self.delivery = delivery
        self.skills = skills
        self.llm = llm
        self.episodic = episodic
        self.recall = recall
        self.sleeptime = sleeptime
        self.heartbeat_seconds = heartbeat_seconds
        self.default_llm_config = default_llm_config or LLMConfig(
            api_key="unused", model="default"
        )
        self.timezone = timezone
        self._scheduler = AsyncIOScheduler()
        self._started = False
        self._on_job_mutated: Callable[[], None] | None = None

        policy = OutreachPolicy(
            idle_seconds=outreach_idle_hours * 3600,
            cooldown_seconds=outreach_cooldown_hours * 3600,
            max_per_day=outreach_max_per_day,
        )
        self.heartbeat = HeartbeatLoop(
            activity,
            interval_seconds=heartbeat_seconds,
            policy=policy,
            on_outreach=self._handle_outreach,
            open_topic_checker=self._has_open_topic,
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def _has_open_topic(self, session_id: str) -> bool:
        """True when episodic (7d) or recall hot window suggests unfinished context."""
        if self.episodic is not None:
            events = self.episodic.list_events(session_id=session_id, limit=10)
            if not events:
                events = self.episodic.list_events(limit=10)
            cutoff = datetime.now() - timedelta(days=7)
            for e in events:
                created = e.created_at
                if created is None:
                    return True
                if created.tzinfo is not None:
                    created = created.replace(tzinfo=None)
                if created >= cutoff:
                    return True
        if self.recall is not None:
            try:
                if self.recall.list_hot(session_id, limit=1):
                    return True
            except Exception:  # noqa: BLE001
                pass
        # Mere activity must not count — that would fire outreach for every idle chat.
        return False

    async def start(self) -> None:
        if self._started:
            return
        specs = builtin_job_specs()
        self.store.ensure_builtin_jobs(
            [
                (
                    s.id,
                    "cron",
                    s.cron,
                    s.description,
                    s.meta,
                )
                for s in specs
            ]
        )
        self._scheduler.add_job(
            self._heartbeat_tick,
            IntervalTrigger(seconds=self.heartbeat_seconds),
            id="heartbeat",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._resync_jobs()
        self._scheduler.start()
        self._started = True
        logger.info(
            "ProactiveLoop started (heartbeat=%ss)", self.heartbeat_seconds
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        logger.info("ProactiveLoop stopped")

    def _resync_jobs(self) -> None:
        """Register/update APScheduler jobs from the store."""
        # Remove non-heartbeat jobs
        for job in list(self._scheduler.get_jobs()):
            if job.id == "heartbeat":
                continue
            try:
                self._scheduler.remove_job(job.id)
            except Exception:  # noqa: BLE001
                pass
        for stored in self.store.list_jobs():
            if not stored.enabled:
                continue
            self._add_aps_job(stored)

    def resync(self) -> None:
        if self._started:
            self._resync_jobs()

    def _add_aps_job(self, stored: StoredJob) -> None:
        job_id = f"job:{stored.id}"
        if stored.kind == "cron" and stored.cron:
            parts = stored.cron.split()
            if len(parts) != 5:
                logger.warning("invalid cron for %s: %s", stored.id, stored.cron)
                return
            minute, hour, day, month, dow = parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=dow,
            )
        elif stored.kind == "date" and stored.run_at is not None:
            if stored.run_at < time.time() - 1:
                # Past one-shot: skip unless re-enabled via trigger API
                return
            trigger = DateTrigger(run_date=datetime.fromtimestamp(stored.run_at))
        else:
            return

        async def _runner(jid: str = stored.id) -> None:
            await self.run_job(jid)

        self._scheduler.add_job(
            _runner,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    async def _heartbeat_tick(self) -> None:
        try:
            await self.heartbeat.tick()
            await self._check_due_reminders()
        except Exception:  # noqa: BLE001
            logger.exception("heartbeat tick failed")

    async def _check_due_reminders(self) -> None:
        """Fire past-due one-shot jobs that APScheduler may have missed."""
        now = time.time()
        for job in self.store.list_jobs():
            if not job.enabled or job.kind != "date" or job.run_at is None:
                continue
            if job.run_at <= now:
                # Claim before notify to avoid double-fire with DateTrigger.
                claimed = self.store.patch_job(job.id, enabled=False)
                if claimed is None or claimed.enabled:
                    continue
                await self.run_job(job.id, already_claimed=True)

    async def _handle_outreach(self, session_id: str) -> None:
        body = await self._generate_with_skill(
            skill_name="proactive_outreach",
            session_id=session_id,
            user_prompt=(
                "The user has been away. Write one short warm check-in "
                "(1-2 sentences, Chinese if prior context is Chinese)."
            ),
            fallback="嗨，想你了。最近还好吗？有什么想聊的随时叫我。",
        )
        await self.delivery.notify(
            "FAE 想聊聊",
            body,
            session_id=session_id,
            source="proactive_outreach",
        )

    async def run_job(
        self, job_id: str, *, already_claimed: bool = False
    ) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            return {"ok": False, "error": "not_found"}
        # Claim one-shots before side effects so APS + heartbeat cannot double-fire.
        if job.kind == "date" and not already_claimed and job.enabled:
            self.store.patch_job(job_id, enabled=False)
            self.resync()
        if job_id == "daily_checkin":
            return await self._run_daily_checkin(job)
        if job_id == "weekly_recap":
            return await self._run_weekly_recap(job)
        # Custom reminder
        title = job.title or "提醒"
        body = job.body or job.title
        try:
            await self.delivery.notify(
                title, body, session_id="", source=f"job:{job_id}"
            )
        except Exception:  # noqa: BLE001
            logger.exception("notify failed for job=%s", job_id)
            return {"ok": False, "id": job_id, "error": "notify_failed"}
        if job.kind == "date" and already_claimed:
            self.resync()
        return {"ok": True, "id": job_id, "title": title}

    async def _run_daily_checkin(self, job: StoredJob) -> dict[str, Any]:
        context = self._yesterday_context()
        skill = (job.meta or {}).get("skill", "daily_check_in")
        body = await self._generate_with_skill(
            skill_name=str(skill),
            session_id="default",
            user_prompt=(
                "Write a brief daily check-in for the user based on this "
                f"yesterday context:\n{context}\n"
                "Keep it under 80 words."
            ),
            fallback="早上好！新的一天开始了，今天想优先做哪一件事？",
        )
        await self.delivery.notify(
            "每日问候", body, source="daily_checkin"
        )
        return {"ok": True, "id": job.id}

    async def _run_weekly_recap(self, job: StoredJob) -> dict[str, Any]:
        context = self._week_context()
        if self.sleeptime is not None:
            try:
                await self.sleeptime.consolidate_now("default")
            except Exception:  # noqa: BLE001
                logger.debug("weekly consolidate failed", exc_info=True)
        body = await self._generate_with_skill(
            skill_name="daily_check_in",
            session_id="default",
            user_prompt=(
                "Write a short weekly recap (bullet-friendly prose) from:\n"
                f"{context}"
            ),
            fallback="本周过得怎么样？有想继续跟进的事可以告诉我。",
        )
        await self.delivery.notify(
            "周报", body, source="weekly_recap"
        )
        return {"ok": True, "id": job.id}

    def _yesterday_context(self) -> str:
        lines: list[str] = []
        if self.episodic is not None:
            for e in self.episodic.list_events(limit=15):
                lines.append(f"- [{e.kind}] {e.summary}")
        return "\n".join(lines) if lines else "(no recent episodic events)"

    def _week_context(self) -> str:
        return self._yesterday_context()

    async def _generate_with_skill(
        self,
        *,
        skill_name: str,
        session_id: str,
        user_prompt: str,
        fallback: str,
    ) -> str:
        if self.llm is None or self.skills is None:
            return fallback
        try:
            req = ChatRequest(
                config=self.default_llm_config,
                messages=[ChatMessage(role="user", content=user_prompt)],
            )
            prepared, activation = self.skills.prepare_activated_request(
                req,
                [skill_name],
                session_id=session_id,
                respect_cooldown=False,
            )
            if skill_name not in activation.active and not activation.active:
                # skill missing/disabled
                prepared = req
            if not prepared.config.api_key or prepared.config.api_key == "unused":
                return fallback
            resp = await self.llm.chat(prepared)
            text = (resp.content or "").strip()
            return text or fallback
        except Exception:  # noqa: BLE001
            logger.debug("LLM generate failed; using fallback", exc_info=True)
            return fallback

    def job_next_run(self, job_id: str) -> float | None:
        aps_id = f"job:{job_id}"
        try:
            job = self._scheduler.get_job(aps_id)
        except Exception:  # noqa: BLE001
            return None
        if job is None or job.next_run_time is None:
            stored = self.store.get_job(job_id)
            if stored and stored.run_at and stored.enabled:
                return stored.run_at
            return None
        return job.next_run_time.timestamp()
