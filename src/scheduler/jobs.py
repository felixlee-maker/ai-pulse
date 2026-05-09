"""定时任务调度模块"""

import asyncio
from datetime import datetime
from typing import Callable, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class Scheduler:
    """定时任务调度器"""

    def __init__(self, timezone: str = "Asia/Shanghai"):
        """
        Args:
            timezone: 时区
        """
        self.timezone = timezone
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._jobs = {}

    def add_cron_job(
        self,
        func: Callable,
        cron_expr: str,
        job_id: str,
        name: Optional[str] = None,
        **kwargs,
    ) -> None:
        """添加 Cron 定时任务

        Args:
            func: 要执行的函数
            cron_expr: Cron 表达式 (分 时 日 月 周)
            job_id: 任务 ID
            name: 任务名称
            **kwargs: 传递给函数的参数
        """
        # 解析 cron 表达式
        parts = cron_expr.split()
        if len(parts) == 5:
            minute, hour, day, month, day_of_week = parts
        else:
            raise ValueError(f"无效的 cron 表达式: {cron_expr}")

        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=self.timezone,
        )

        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = job
        print(f"添加定时任务: {name or job_id} - {cron_expr}")

    def add_interval_job(
        self,
        func: Callable,
        minutes: int,
        job_id: str,
        name: Optional[str] = None,
        **kwargs,
    ) -> None:
        """添加间隔执行任务

        Args:
            func: 要执行的函数
            minutes: 间隔分钟数
            job_id: 任务 ID
            name: 任务名称
            **kwargs: 传递给函数的参数
        """
        job = self.scheduler.add_job(
            func,
            "interval",
            minutes=minutes,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = job
        print(f"添加间隔任务: {name or job_id} - 每 {minutes} 分钟")

    def remove_job(self, job_id: str) -> None:
        """移除任务"""
        if job_id in self._jobs:
            self.scheduler.remove_job(job_id)
            del self._jobs[job_id]

    def start(self) -> None:
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            print(f"调度器已启动 (时区: {self.timezone})")

    def shutdown(self, wait: bool = True) -> None:
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            print("调度器已关闭")

    def get_jobs(self) -> list:
        """获取所有任务"""
        return self.scheduler.get_jobs()

    def print_jobs(self) -> None:
        """打印所有任务"""
        jobs = self.get_jobs()
        if not jobs:
            print("当前没有定时任务")
            return

        print("\n当前定时任务:")
        print("-" * 60)
        for job in jobs:
            next_run = job.next_run_time
            next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "未调度"
            print(f"  {job.name}: 下次执行 {next_run_str}")
        print("-" * 60)
