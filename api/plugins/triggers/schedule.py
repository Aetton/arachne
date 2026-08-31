"""Schedule trigger — cron-fire scenarios and host shared lifecycle jobs.

    triggers:
      - {type: schedule, cron: "0 2 * * *"}

Uses a shared AsyncIOScheduler started by the app lifespan. Managed-machine TTL
cleanup is registered on the same scheduler so there is one timing engine inside
Arachne rather than a second hidden cron mechanism.
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

    # Import lazily to avoid a module cycle: managed_machines uses this scheduler
    # only when the application has already loaded plugins and the bus.
    from managed_machines import start_reaper
    start_reaper()


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
