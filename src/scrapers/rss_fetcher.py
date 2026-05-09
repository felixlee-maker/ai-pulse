"""RSS 数据源爬虫"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from dataclasses import dataclass
import httpx
import feedparser

from .base import BaseScraper
from ..storage.models import ArticleSchema


@dataclass
class RSSFeed:
    """RSS 订阅源"""
    name: str
    url: str
    category: str = ""
    domain: str = "ai"


class RSSFetcher(BaseScraper):
    """RSS 数据源爬虫

    支持直接 RSS 源和自建 RSSHub 路由。
    """

    def __init__(
        self,
        max_age_days: int = 1,
        **kwargs
    ):
        """
        Args:
            max_age_days: 只获取最近 N 天的文章
        """
        super().__init__(**kwargs)
        self.max_age_days = max_age_days

    async def _fetch_feed(self, url: str, source_name: str = "") -> Optional[feedparser.FeedParserDict]:
        """获取并解析 RSS feed"""
        try:
            response = await self.fetch(url)
            if response and response.text:
                feed = feedparser.parse(response.text)
                if feed.bozo and feed.bozo_exception:
                    if not feed.entries:
                        print(f"RSS 解析失败 [{source_name or url}]: {feed.bozo_exception}")
                return feed
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}"
            if e.response.status_code == 403:
                error_msg += " (访问被拒绝)"
            elif e.response.status_code == 404:
                error_msg += " (路由不存在)"
            elif e.response.status_code == 503:
                error_msg += " (服务不可用)"
            print(f"获取 RSS 失败 [{source_name or url}]: {error_msg}")
        except httpx.TimeoutException:
            print(f"获取 RSS 超时 [{source_name or url}]")
        except httpx.ConnectError:
            print(f"获取 RSS 连接失败 [{source_name or url}]")
        except Exception as e:
            print(f"获取 RSS 失败 [{source_name or url}]: {type(e).__name__}: {e}")
        return None

    def _parse_publish_time(self, entry) -> Optional[datetime]:
        """解析发布时间"""
        time_fields = ['published_parsed', 'updated_parsed', 'created_parsed']

        for field in time_fields:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    import time
                    time_struct = getattr(entry, field)
                    return datetime.fromtimestamp(time.mktime(time_struct), tz=timezone.utc)
                except Exception:
                    continue

        time_str_fields = ['published', 'updated', 'created']
        for field in time_str_fields:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    from email.utils import parsedate_to_datetime
                    return parsedate_to_datetime(getattr(entry, field))
                except Exception:
                    continue

        return None

    def _is_within_time_range(self, publish_time: Optional[datetime]) -> bool:
        """检查文章是否在时间范围内"""
        if not publish_time:
            return True

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.max_age_days)

        if publish_time.tzinfo is None:
            publish_time = publish_time.replace(tzinfo=timezone.utc)

        return publish_time >= cutoff

    def _parse_entry(self, entry, feed_title: str = "", feed_domain: str = "ai") -> Optional[ArticleSchema]:
        """解析单个 RSS 条目"""
        try:
            title = entry.get('title', '').strip()
            url = entry.get('link', '').strip()

            if not title or not url:
                return None

            publish_time = self._parse_publish_time(entry)

            if not self._is_within_time_range(publish_time):
                return None

            summary = ""
            if hasattr(entry, 'summary'):
                summary = entry.summary
            elif hasattr(entry, 'description'):
                summary = entry.description

            if summary:
                import re
                summary = re.sub(r'<[^>]+>', '', summary)
                summary = summary.strip()[:500]

            author = feed_title

            return ArticleSchema(
                title=title,
                url=url,
                author=author,
                summary=summary,
                publish_time=publish_time.replace(tzinfo=None) if publish_time else None,
                crawl_time=datetime.utcnow(),
                domain=feed_domain,
            )

        except Exception as e:
            print(f"解析 RSS 条目失败: {e}")
            return None

    async def search_by_account(self, account_name: str, max_articles: int = 10) -> List[ArticleSchema]:
        """根据账号搜索文章 (未实现)"""
        return []

    async def search_by_keyword(self, keyword: str, max_articles: int = 10) -> List[ArticleSchema]:
        """根据关键词搜索文章 (RSS 源暂不支持)"""
        return []

    async def fetch_from_feed(self, feed: RSSFeed) -> List[ArticleSchema]:
        """从单个 RSS 源获取文章"""
        articles = []

        feed_data = await self._fetch_feed(feed.url, feed.name)
        if not feed_data:
            print(f"获取 RSS 失败 [{feed.name}]: 无响应")
            return articles
        if not feed_data.entries:
            print(f"获取 RSS 失败 [{feed.name}]: 无文章条目")
            return articles

        feed_title = feed.name

        entries = feed_data.entries
        if "arXiv" in feed.name:
            entries = entries[:1]
        else:
            entries = entries[:10]

        filtered_count = 0
        for entry in entries:
            article = self._parse_entry(entry, feed_title, feed.domain)
            if article:
                articles.append(article)
            else:
                filtered_count += 1

        if filtered_count > 0 and not articles:
            print(f"[{feed.name}] 所有 {filtered_count} 篇文章超出时间范围 ({self.max_age_days} 天)")

        return articles

    async def fetch_from_feeds(self, feeds: List[RSSFeed], concurrency: int = 5) -> List[ArticleSchema]:
        """从多个 RSS 源获取文章（并发）"""
        all_articles = []
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch_single(feed):
            async with semaphore:
                try:
                    import random
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    articles = await self.fetch_from_feed(feed)
                    if articles:
                        print(f"从 '{feed.name}' 获取到 {len(articles)} 篇文章")
                    return articles
                except Exception as e:
                    print(f"获取 '{feed.name}' 失败: {e}")
                    return []

        tasks = [_fetch_single(feed) for feed in feeds]
        results = await asyncio.gather(*tasks)

        for res in results:
            all_articles.extend(res)

        return all_articles
