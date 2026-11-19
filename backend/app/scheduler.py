# -*- coding: utf-8 -*-
"""定时调度：按设置每日 / 每周自动抓取。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import database, crawler

_scheduler: BackgroundScheduler | None = None
JOB_ID = "policy_crawl"


def _trigger():
    schedule = database.get_setting("schedule", "daily")
    if schedule == "weekly":
        weekday = int(database.get_setting("weekly_weekday", "1"))
        hour = int(database.get_setting("weekly_hour", "6"))
        return CronTrigger(day_of_week=weekday, hour=hour, minute=0)
    hour = int(database.get_setting("daily_hour", "6"))
    return CronTrigger(hour=hour, minute=0)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(crawler.run_all, trigger=_trigger(), id=JOB_ID, replace_existing=True,
                       misfire_grace_time=3600)
    _scheduler.start()
    return _scheduler


def reload_scheduler():
    """设置变更后重建触发器。"""
    global _scheduler
    if _scheduler is None:
        start_scheduler()
        return
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)
    _scheduler.add_job(crawler.run_all, trigger=_trigger(), id=JOB_ID, replace_existing=True,
                       misfire_grace_time=3600)


def next_run_time():
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job and job.next_run_time else None
