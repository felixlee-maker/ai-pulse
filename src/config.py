"""配置加载模块"""

import os
from pathlib import Path
from typing import List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


class RSSFeedConfig(BaseModel):
    """RSS 源配置"""

    name: str
    url: str
    category: str = ""
    domain: str = "ai"


class RSSConfig(BaseModel):
    """RSS 配置"""

    enabled: bool = True
    max_age_days: int = 1
    delay_seconds: float = 2.0
    feeds: List[RSSFeedConfig] = []


class ScraperConfig(BaseModel):
    """爬虫配置"""

    source: str = "rss"
    enabled: bool = True
    timeout: int = 30
    max_retries: int = 3
    rss: RSSConfig = RSSConfig()


class FilterConfig(BaseModel):
    """过滤器配置"""

    enabled: bool = True
    # AI 后端: "claude-code" (使用 claude CLI, 无需 API key) 或 "openai"
    ai_backend: str = "claude-code"
    relevance_threshold: float = 0.6
    # Claude Code 并发数（避免同时启动过多进程）
    max_concurrency: int = 3
    keywords_include: List[str] = []
    keywords_exclude: List[str] = []


class NotifierConfig(BaseModel):
    """通知器配置"""

    enabled: bool = True
    lark_webhook_url: Optional[str] = None
    lark_max_items: int = 10
    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_smtp_user: Optional[str] = None
    email_smtp_password: Optional[str] = None
    email_to: Optional[str] = None


class SchedulerJobConfig(BaseModel):
    """调度任务配置"""

    name: str
    cron: str
    enabled: bool = True


class SchedulerConfig(BaseModel):
    """调度器配置"""

    timezone: str = "Asia/Shanghai"
    jobs: List[SchedulerJobConfig] = []


class AppConfig(BaseModel):
    """应用配置"""

    name: str = "AI-Pulse"
    version: str = "1.0.0"

    scraper: ScraperConfig = ScraperConfig()
    filter: FilterConfig = FilterConfig()
    notifier: NotifierConfig = NotifierConfig()
    scheduler: SchedulerConfig = SchedulerConfig()

    database_url: str = "sqlite:///data/articles.db"

    # OpenAI (openai 后端)
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # Claude Code (claude-code 后端)
    claude_model: str = "claude-haiku-4-5"


def load_config(config_dir: str = "config") -> AppConfig:
    """加载配置"""
    load_dotenv()

    def env_int(key: str, default: int) -> int:
        """读取整型环境变量，空值或非法值时回退到默认。

        GitHub Actions 中未配置的 secret 会被注入为空字符串而非缺省，
        若直接 int('') 会抛出 ValueError，此处统一兜底。
        """
        raw = os.getenv(key)
        if raw is None or raw.strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def env_str(key: str, default=None):
        """空字符串视为未设置。"""
        raw = os.getenv(key)
        if raw is None or raw == "":
            return default
        return raw

    config_path = Path(config_dir)

    # 加载主配置
    main_config_file = config_path / "config.yaml"
    main_config = {}
    if main_config_file.exists():
        with open(main_config_file, "r", encoding="utf-8") as f:
            main_config = yaml.safe_load(f) or {}

    # 解析 RSSHUB_BASE_URL 用于替换 feed URL 中的占位符
    rsshub_base = env_str(
        "RSSHUB_BASE_URL",
        main_config.get("scraper", {}).get("rss", {}).get("rsshub_base", ""),
    ).rstrip("/")

    config = AppConfig(
        name=main_config.get("app", {}).get("name", "AI-Pulse"),
        version=main_config.get("app", {}).get("version", "1.0.0"),
        scraper=ScraperConfig(
            source=main_config.get("scraper", {}).get("source", "rss"),
            timeout=main_config.get("scraper", {}).get("request", {}).get("timeout", 30),
            max_retries=main_config.get("scraper", {}).get("request", {}).get("max_retries", 3),
            rss=RSSConfig(
                enabled=main_config.get("scraper", {}).get("rss", {}).get("enabled", True),
                max_age_days=main_config.get("scraper", {}).get("rss", {}).get("max_age_days", 1),
                delay_seconds=main_config.get("scraper", {}).get("rss", {}).get("delay_seconds", 2.0),
                feeds=[
                    RSSFeedConfig(**{
                        **feed,
                        "url": feed.get("url", "").replace("${RSSHUB_BASE_URL}", rsshub_base),
                    })
                    for feed in main_config.get("scraper", {}).get("rss", {}).get("feeds", [])
                ],
            ),
        ),
        filter=FilterConfig(
            enabled=main_config.get("filter", {}).get("enabled", True),
            ai_backend=env_str("AI_BACKEND", main_config.get("filter", {}).get("ai_backend", "claude-code")),
            relevance_threshold=main_config.get("filter", {}).get("relevance_threshold", 0.6),
            max_concurrency=env_int("AI_MAX_CONCURRENCY", main_config.get("filter", {}).get("max_concurrency", 3)),
            keywords_include=main_config.get("filter", {}).get("keywords", {}).get("include", []),
            keywords_exclude=main_config.get("filter", {}).get("keywords", {}).get("exclude", []),
        ),
        notifier=NotifierConfig(
            enabled=main_config.get("notifier", {}).get("lark", {}).get("enabled", True),
            lark_webhook_url=env_str("LARK_WEBHOOK_URL"),
            lark_max_items=env_int("LARK_MAX_ITEMS", 10),
            email_enabled=bool(env_str("EMAIL_SMTP_USER") and env_str("EMAIL_SMTP_PASSWORD")),
            email_smtp_host=env_str("EMAIL_SMTP_HOST", "smtp.gmail.com"),
            email_smtp_port=env_int("EMAIL_SMTP_PORT", 587),
            email_smtp_user=env_str("EMAIL_SMTP_USER"),
            email_smtp_password=env_str("EMAIL_SMTP_PASSWORD"),
            email_to=env_str("EMAIL_TO"),
        ),
        scheduler=SchedulerConfig(
            timezone=main_config.get("scheduler", {}).get("timezone", "Asia/Shanghai"),
            jobs=[
                SchedulerJobConfig(**job)
                for job in main_config.get("scheduler", {}).get("jobs", [])
            ],
        ),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/articles.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5"),
    )

    return config
