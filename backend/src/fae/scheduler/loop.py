"""ProactiveLoop: APScheduler wiring for heartbeat + builtin/custom jobs."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from fae.agent.prepare import prepare_chat_request
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig
from fae.memory.defaults import DEFAULT_HUMAN
from fae.scheduler.delivery import DEFAULT_SESSION_ID, NotificationDelivery
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
    from fae.pipecat.services.letta_memory import LettaMemoryService
    from fae.scheduler.activity import ActivityTracker

logger = logging.getLogger("fae.scheduler.loop")

_IDENTITY_HINT = re.compile(
    r"(名字|姓名|我叫|住在|忌|过敏|timezone|my name|i live|prefer)",
    re.I,
)


class ProactiveLoop:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        activity: ActivityTracker,
        delivery: NotificationDelivery,
        skills: SkillRuntime | None = None,
        llm: LLMClient | None = None,
        memory: LettaMemoryService | None = None,
        episodic: EpisodicStore | None = None,
        recall: RecallStore | None = None,
        sleeptime: SleeptimeScheduler | None = None,
        heartbeat_seconds: float = 30.0,
        outreach_idle_hours: float = 6.0,
        outreach_cooldown_hours: float = 12.0,
        outreach_max_per_day: int = 1,
        default_llm_config: LLMConfig | None = None,
        timezone: str = "local",
        default_city: str = "",
        default_timezone: str = "",
    ) -> None:
        self.store = store
        self.activity = activity
        self.delivery = delivery
        self.skills = skills
        self.llm = llm
        self.memory = memory
        self.episodic = episodic
        self.recall = recall
        self.sleeptime = sleeptime
        self.heartbeat_seconds = heartbeat_seconds
        self.default_llm_config = default_llm_config or LLMConfig(
            api_key="unused", model="default"
        )
        self.timezone = timezone
        self.default_city = default_city
        self.default_timezone = default_timezone
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
            store=store,
            prefs_getter=store.get_prefs,
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def _text_suggests_open_topic(self, text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        if "?" in t or "？" in t:
            return True
        return bool(_IDENTITY_HINT.search(t))

    async def _has_open_topic(self, session_id: str) -> bool:
        """True when human is personalized or recent user text suggests open context.

        Arbitrary 7-day episodic alone is not enough.
        """
        sid = (session_id or "").strip() or DEFAULT_SESSION_ID

        if self.memory is not None and getattr(self.memory, "enabled", False):
            client = getattr(self.memory, "client", None)
            if client is not None:
                try:
                    human = (await client.get_block("human")).strip()
                    if human and human != DEFAULT_HUMAN.strip():
                        return True
                except Exception:  # noqa: BLE001
                    logger.debug("open_topic human read failed", exc_info=True)

        if self.recall is not None:
            try:
                for turn in self.recall.list_hot(sid, limit=12):
                    if self._text_suggests_open_topic(turn.user_text or ""):
                        return True
                    if self._text_suggests_open_topic(turn.assistant_text or ""):
                        return True
            except Exception:  # noqa: BLE001
                logger.debug("open_topic recall failed", exc_info=True)

        if self.episodic is not None:
            cutoff = datetime.now() - timedelta(days=7)
            try:
                events = self.episodic.list_events(session_id=sid, limit=15)
                if not events:
                    events = self.episodic.list_events(limit=15)
                for e in events:
                    created = e.created_at
                    if created is not None:
                        if created.tzinfo is not None:
                            created = created.replace(tzinfo=None)
                        if created < cutoff:
                            continue
                    summary = getattr(e, "summary", "") or ""
                    if self._text_suggests_open_topic(summary):
                        return True
            except Exception:  # noqa: BLE001
                logger.debug("open_topic episodic failed", exc_info=True)

        return False

    async def start(self) -> None:
        if self._started:
            return
        self.activity.bind_store(self.store)
        self.heartbeat.bind_store(self.store)
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
                claimed = self.store.patch_job(job.id, enabled=False)
                if claimed is None or claimed.enabled:
                    continue
                await self.run_job(job.id, already_claimed=True)

    async def _handle_outreach(self, session_id: str) -> None:
        sid = (session_id or "").strip() or DEFAULT_SESSION_ID
        body = await self._generate_with_skill(
            skill_name="proactive_outreach",
            session_id=sid,
            user_prompt=(
                "The user has been away. Write one short warm check-in "
                "(1-2 sentences, Chinese if prior context is Chinese). "
                "Use the user's name or recent topics from memory when available."
            ),
            fallback="嗨，想你了。最近还好吗？有什么想聊的随时叫我。",
        )
        await self.delivery.notify(
            "FAE 想聊聊",
            body,
            session_id=sid,
            source="proactive_outreach",
            speak=True,
        )

    async def run_job(
        self, job_id: str, *, already_claimed: bool = False
    ) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            return {"ok": False, "error": "not_found"}
        if job.kind == "date" and not already_claimed and job.enabled:
            self.store.patch_job(job_id, enabled=False)
            self.resync()
        if job_id == "daily_checkin":
            return await self._run_daily_checkin(job)
        if job_id == "weekly_recap":
            return await self._run_weekly_recap(job)
        title = job.title or "提醒"
        body = job.body or job.title
        try:
            await self.delivery.notify(
                title,
                body,
                session_id=DEFAULT_SESSION_ID,
                source=f"job:{job_id}",
                speak=True,
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
            session_id=DEFAULT_SESSION_ID,
            user_prompt=(
                "Write a brief daily check-in for the user based on this "
                f"yesterday context:\n{context}\n"
                "Keep it under 80 words."
            ),
            fallback="早上好！新的一天开始了，今天想优先做哪一件事？",
        )
        await self.delivery.notify(
            "每日问候",
            body,
            session_id=DEFAULT_SESSION_ID,
            source="daily_checkin",
            speak=True,
        )
        return {"ok": True, "id": job.id}

    async def _run_weekly_recap(self, job: StoredJob) -> dict[str, Any]:
        context = self._week_context()
        if self.sleeptime is not None:
            try:
                await self.sleeptime.consolidate_now(DEFAULT_SESSION_ID)
            except Exception:  # noqa: BLE001
                logger.debug("weekly consolidate failed", exc_info=True)
        body = await self._generate_with_skill(
            skill_name="daily_check_in",
            session_id=DEFAULT_SESSION_ID,
            user_prompt=(
                "Write a short weekly recap (bullet-friendly prose) from:\n"
                f"{context}"
            ),
            fallback="本周过得怎么样？有想继续跟进的事可以告诉我。",
        )
        await self.delivery.notify(
            "周报",
            body,
            session_id=DEFAULT_SESSION_ID,
            source="weekly_recap",
            speak=True,
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

    def _llm_ready(self) -> bool:
        key = (self.default_llm_config.api_key or "").strip()
        return bool(key) and key != "unused"

    async def _alert_generate_failure(
        self, session_id: str, reason: str, detail: str
    ) -> None:
        sid = (session_id or "").strip() or DEFAULT_SESSION_ID
        title = (
            "主动生成失败 / 未配置模型"
            if "配置" in reason or "key" in reason.lower() or "未配置" in reason
            else "主动生成失败"
        )
        body = f"{reason}：{detail}"[:280]
        logger.warning("proactive generate failed: %s — %s", reason, detail)
        try:
            await self.delivery.notify(
                title,
                body,
                session_id=sid,
                source="proactive_alert",
                speak=False,
            )
        except Exception:  # noqa: BLE001
            logger.debug("proactive alert notify failed", exc_info=True)

    async def _generate_with_skill(
        self,
        *,
        skill_name: str,
        session_id: str,
        user_prompt: str,
        fallback: str,
    ) -> str:
        sid = (session_id or "").strip() or DEFAULT_SESSION_ID

        if self.llm is None:
            await self._alert_generate_failure(
                sid, "未配置模型", "LLM client unavailable on server"
            )
            return fallback

        if not self._llm_ready():
            await self._alert_generate_failure(
                sid,
                "未配置模型",
                "Set PROACTIVE_LLM_API_KEY or DASHSCOPE_API_KEY on the server",
            )
            return fallback

        try:
            req = ChatRequest(
                config=self.default_llm_config,
                messages=[ChatMessage(role="user", content=user_prompt)],
                session_id=sid,
            )
            prepared, _activation, _city = await prepare_chat_request(
                req,
                session_id=sid,
                memory=self.memory,
                skills=None,
                default_city=self.default_city,
                default_timezone=self.default_timezone,
            )
            if self.skills is not None:
                prepared, activation = self.skills.prepare_activated_request(
                    prepared,
                    [skill_name],
                    session_id=sid,
                    respect_cooldown=False,
                )
                if skill_name not in activation.active and not activation.active:
                    pass  # skill missing/disabled — still chat with memory context
            resp = await self.llm.chat(prepared)
            text = (resp.content or "").strip()
            if not text:
                await self._alert_generate_failure(
                    sid, "主动生成失败", "empty model response"
                )
                return fallback
            return text
        except Exception as exc:  # noqa: BLE001
            await self._alert_generate_failure(
                sid, "主动生成失败", str(exc)[:200] or exc.__class__.__name__
            )
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
