"""Schedule trigger — cron-fire a scenario with default params.

    triggers:
      - {type: schedule, cron: "0 2 * * *"}

Uses a shared AsyncIOScheduler started by the app lifespan.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.trigger import BaseTrigger
from core.registry import register_trigger

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler():
    sch = get_scheduler()
    if not sch.running:
        sch.start()


@register_trigger
class ScheduleTrigger(BaseTrigger):
    NAME = "schedule"

    def setup(self, scenario_key: str, cfg: dict) -> None:
        cron = cfg.get("cron")
        if not cron:
            return
        params = cfg.get("params", {})
        trigger = CronTrigger.from_crontab(cron)

        async def _job():
            await self.fire(scenario_key, params, source="schedule")

        get_scheduler().add_job(
            _job,
            trigger=trigger,
            id=f"sched:{scenario_key}",
            replace_existing=True,
        )
