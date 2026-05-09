"""AI-Pulse 主程序入口"""

import asyncio
import argparse
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .config import load_config, AppConfig
from .storage import Database
from .scrapers import RSSFetcher
from .exporters import DailyReportExporter
from .scrapers.rss_fetcher import RSSFeed
from .processors import AIFilter, Deduplicator
from .notifiers import LarkNotifier, EmailNotifier
from .scheduler import Scheduler

console = Console()


class AIPulse:
    """AI-Pulse 主应用类"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.database_url)
        self.rss_fetcher: Optional[RSSFetcher] = None
        self.ai_filter: Optional[AIFilter] = None
        self.lark_notifier: Optional[LarkNotifier] = None
        self.email_notifier: Optional[EmailNotifier] = None
        self.scheduler: Optional[Scheduler] = None
        self._running = False

    def _init_components(self):
        """初始化组件"""
        if self.config.scraper.source == "rss":
            self.rss_fetcher = RSSFetcher(
                max_age_days=self.config.scraper.rss.max_age_days,
                timeout=self.config.scraper.timeout,
                max_retries=self.config.scraper.max_retries,
                delay_seconds=self.config.scraper.rss.delay_seconds,
            )

        # 初始化 AI 过滤器
        if self.config.filter.enabled:
            model = self.config.claude_model if self.config.filter.ai_backend == "claude-code" else self.config.openai_model
            self.ai_filter = AIFilter(
                backend=self.config.filter.ai_backend,
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url,
                model=model,
                relevance_threshold=self.config.filter.relevance_threshold,
                keywords_include=self.config.filter.keywords_include,
                keywords_exclude=self.config.filter.keywords_exclude,
                max_concurrency=self.config.filter.max_concurrency,
            )

        # 初始化飞书通知器
        if self.config.notifier.enabled and self.config.notifier.lark_webhook_url:
            self.lark_notifier = LarkNotifier(self.config.notifier.lark_webhook_url)

        # 初始化邮件通知器
        if self.config.notifier.email_enabled:
            try:
                self.email_notifier = EmailNotifier(
                    smtp_host=self.config.notifier.email_smtp_host,
                    smtp_port=self.config.notifier.email_smtp_port,
                    smtp_user=self.config.notifier.email_smtp_user,
                    smtp_password=self.config.notifier.email_smtp_password,
                    to_address=self.config.notifier.email_to,
                )
            except ValueError as e:
                console.print(f"[yellow]邮件通知器初始化失败: {e}[/yellow]")

    async def fetch_and_process(self, notify: bool = True) -> dict:
        """抓取并处理文章"""
        stats = {
            "fetched": 0,
            "new": 0,
            "relevant": 0,
            "notified": 0,
            "errors": [],
        }

        console.print(f"\n[bold blue]开始抓取文章...[/bold blue]")

        # 抓取文章
        try:
            if self.rss_fetcher:
                articles = []
                feeds = [
                    RSSFeed(name=f.name, url=f.url, category=f.category, domain=f.domain)
                    for f in self.config.scraper.rss.feeds
                ]
                if feeds:
                    console.print(f"  从 {len(feeds)} 个 RSS 源获取...")
                    articles = await self.rss_fetcher.fetch_from_feeds(feeds)
                    console.print(f"    获取到 {len(articles)} 篇文章")
                else:
                    console.print("[yellow]  警告: 没有配置任何 RSS 源[/yellow]")
            else:
                console.print("[red]错误: 未配置有效的数据源[/red]")
                return stats

            stats["fetched"] = len(articles)
        except Exception as e:
            error_msg = f"抓取失败: {e}"
            stats["errors"].append(error_msg)
            console.print(f"[red]{error_msg}[/red]")
            return stats

        if not articles:
            console.print("[yellow]  没有抓取到新文章[/yellow]")
            return stats

        # 去重
        dedup = Deduplicator(self.db)
        unique_articles = dedup.deduplicate(articles)
        stats["new"] = len(unique_articles)
        console.print(f"  去重后 {len(unique_articles)} 篇新文章")

        if not unique_articles:
            return stats

        # AI 过滤
        relevant_articles = []
        if self.ai_filter:
            console.print("  正在进行 AI 过滤...")
            results = await self.ai_filter.filter_articles(unique_articles)

            for article, filter_result in results:
                article.relevance_score = filter_result.relevance_score
                article.ai_summary = filter_result.ai_summary
                article.is_relevant = filter_result.is_relevant

                saved = self.db.save_article(article)

                if saved:
                    if filter_result.is_relevant and filter_result.relevance_score >= self.config.filter.relevance_threshold:
                        relevant_articles.append(saved)

                    self.db.update_article_relevance(
                        saved.id,
                        filter_result.relevance_score,
                        filter_result.ai_summary,
                        filter_result.is_relevant,
                    )

            stats["relevant"] = len(relevant_articles)
            console.print(f"  AI 过滤后 {len(relevant_articles)} 篇相关文章")
        else:
            for article in unique_articles:
                article.is_relevant = True
                saved = self.db.save_article(article)
                if saved:
                    relevant_articles.append(saved)
            stats["relevant"] = len(relevant_articles)

        # 发送通知
        if notify and relevant_articles:
            beijing_tz = timezone(timedelta(hours=8))
            today = datetime.now(beijing_tz).strftime("%m-%d")
            notified_ids = []

            # 仅当使用 Claude Code CLI 后端时，给标题加上 (Claude) 标记，
            # 用于区分 GitHub Actions（OpenAI 后端）与自部署的推送来源
            backend_tag = "（Claude）" if self.config.filter.ai_backend == "claude-code" else ""

            # 1. 邮件通知：发送全部文章
            if self.email_notifier:
                console.print(f"  发送邮件通知 ({len(relevant_articles)} 篇)...")
                try:
                    email_success = await self.email_notifier.send_digest(
                        relevant_articles,
                        f"🤖 AI 资讯日报 · {today}{backend_tag}"
                    )
                    if email_success:
                        console.print(f"  [green]邮件发送成功[/green]")
                    else:
                        console.print("[red]  邮件发送失败[/red]")
                except Exception as e:
                    console.print(f"[red]  邮件发送失败: {e}[/red]")

            # 2. 飞书通知：只发送 Top N 条（按评分排序）
            if self.lark_notifier:
                max_items = self.config.notifier.lark_max_items
                top_articles = sorted(
                    relevant_articles,
                    key=lambda a: a.relevance_score or 0,
                    reverse=True
                )[:max_items]

                console.print(f"  发送飞书通知 (Top {len(top_articles)} 篇)...")
                try:
                    lark_success = await self.lark_notifier.send_digest(
                        top_articles,
                        f"🤖 AI 资讯速递 · {today}{backend_tag}"
                    )
                    if lark_success:
                        notified_ids = [a.id for a in top_articles]
                        console.print(f"  [green]飞书发送成功[/green]")
                    else:
                        console.print("[red]  飞书发送失败[/red]")
                except Exception as e:
                    error_msg = f"飞书通知失败: {e}"
                    stats["errors"].append(error_msg)
                    console.print(f"[red]  {error_msg}[/red]")

            # 标记所有相关文章为已通知
            if notified_ids or self.email_notifier:
                article_ids = [a.id for a in relevant_articles]
                self.db.mark_as_notified(article_ids)
                stats["notified"] = len(relevant_articles)

        # 导出每日结构化数据（使用全量相关文章，不受飞书推送条数限制）
        if relevant_articles:
            try:
                exporter = DailyReportExporter()
                paths = exporter.export(relevant_articles, stats)
                console.print(f"  [green]每日报告已导出:[/green]")
                console.print(f"    JSON: {paths['json']}")
                console.print(f"    Markdown: {paths['md']}")
            except Exception as e:
                console.print(f"[red]  每日报告导出失败: {e}[/red]")

        return stats

    async def run_once(self):
        """执行一次抓取"""
        self._init_components()
        try:
            stats = await self.fetch_and_process()
            self._print_stats(stats)
        finally:
            if self.rss_fetcher:
                await self.rss_fetcher.close()

    async def run_daemon(self):
        """守护进程模式运行"""
        self._init_components()
        self._running = True

        self.scheduler = Scheduler(self.config.scheduler.timezone)

        for job_config in self.config.scheduler.jobs:
            if job_config.enabled:
                self.scheduler.add_cron_job(
                    self._scheduled_fetch,
                    job_config.cron,
                    job_config.name,
                    name=job_config.name,
                )

        self.scheduler.start()
        self.scheduler.print_jobs()

        console.print("\n[bold green]AI-Pulse 守护进程已启动[/bold green]")
        console.print("按 Ctrl+C 退出\n")

        await self._scheduled_fetch()

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.shutdown()

    async def _scheduled_fetch(self):
        """定时抓取任务"""
        console.print(f"\n[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim] 执行定时抓取")
        try:
            stats = await self.fetch_and_process()
            self._print_stats(stats)
        except Exception as e:
            console.print(f"[red]定时任务执行失败: {e}[/red]")
            if self.lark_notifier:
                await self.lark_notifier.send_error(str(e))

    def shutdown(self):
        """关闭应用"""
        self._running = False
        if self.scheduler:
            self.scheduler.shutdown()
        console.print("\n[yellow]AI-Pulse 已关闭[/yellow]")

    def _print_stats(self, stats: dict):
        """打印统计信息"""
        table = Table(title="处理统计")
        table.add_column("指标", style="cyan")
        table.add_column("数量", style="green")

        table.add_row("抓取文章", str(stats["fetched"]))
        table.add_row("新文章", str(stats["new"]))
        table.add_row("相关文章", str(stats["relevant"]))
        table.add_row("已通知", str(stats["notified"]))

        if stats["errors"]:
            table.add_row("错误", str(len(stats["errors"])), style="red")

        console.print(table)

    def show_status(self):
        """显示状态"""
        stats = self.db.get_statistics()

        table = Table(title="AI-Pulse 状态")
        table.add_column("指标", style="cyan")
        table.add_column("数量", style="green")

        table.add_row("总文章数", str(stats["total_articles"]))
        table.add_row("相关文章", str(stats["relevant_articles"]))
        table.add_row("已通知", str(stats["notified_articles"]))
        table.add_row("今日新增", str(stats["today_articles"]))

        console.print(table)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI-Pulse: AI 资讯聚合监控")
    parser.add_argument(
        "command",
        choices=["run", "daemon", "status", "test-notify"],
        default="run",
        nargs="?",
        help="命令: run(单次运行), daemon(守护进程), status(状态), test-notify(测试通知)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config",
        help="配置目录路径",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="不发送通知",
    )

    args = parser.parse_args()

    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    try:
        config = load_config(args.config)
    except Exception as e:
        console.print(f"[red]配置加载失败: {e}[/red]")
        sys.exit(1)

    # 显示启动信息
    console.print(f"\n[bold blue]{config.name} v{config.version}[/bold blue]")
    console.print(f"RSS 源: {len(config.scraper.rss.feeds)} 个 (最近 {config.scraper.rss.max_age_days} 天)")
    console.print(f"AI 过滤: {'启用' if config.filter.enabled else '禁用'}" + (f" (后端: {config.filter.ai_backend}, 模型: {config.claude_model if config.filter.ai_backend == 'claude-code' else config.openai_model})" if config.filter.enabled else ""))
    console.print(f"飞书通知: {'启用' if config.notifier.enabled else '禁用'}")

    app = AIPulse(config)

    def signal_handler(sig, frame):
        console.print("\n[yellow]收到退出信号...[/yellow]")
        app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.command == "status":
        app.show_status()
    elif args.command == "test-notify":
        asyncio.run(test_notify(config))
    elif args.command == "daemon":
        asyncio.run(app.run_daemon())
    else:  # run
        asyncio.run(app.run_once())


async def test_notify(config: AppConfig):
    """测试通知"""
    if not config.notifier.lark_webhook_url:
        console.print("[red]错误: LARK_WEBHOOK_URL 未配置[/red]")
        return

    notifier = LarkNotifier(config.notifier.lark_webhook_url)
    success = await notifier.send_text("AI-Pulse 通知测试 - 配置成功!")

    if success:
        console.print("[green]通知测试成功![/green]")
    else:
        console.print("[red]通知测试失败[/red]")


if __name__ == "__main__":
    main()
