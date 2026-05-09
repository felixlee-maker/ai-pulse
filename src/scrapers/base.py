"""爬虫基类"""

import asyncio
import random
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..storage.models import ArticleSchema


class BaseScraper(ABC):
    """爬虫基类"""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        delay_seconds: float = 2.0,
        user_agent: Optional[str] = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent or self._get_default_user_agent()
        self._client: Optional[httpx.AsyncClient] = None

    def _get_default_user_agent(self) -> str:
        """获取默认 User-Agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        return random.choice(user_agents)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch(self, url: str, **kwargs) -> httpx.Response:
        """发送 HTTP 请求"""
        client = await self._get_client()
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response

    async def delay(self):
        """请求延迟，避免被封"""
        delay = self.delay_seconds + random.uniform(0, 1)
        await asyncio.sleep(delay)

    @abstractmethod
    async def search_by_account(self, account_name: str, max_articles: int = 10) -> List[ArticleSchema]:
        """根据公众号名称搜索文章"""
        pass

    @abstractmethod
    async def search_by_keyword(self, keyword: str, max_articles: int = 10) -> List[ArticleSchema]:
        """根据关键词搜索文章"""
        pass

    async def scrape_accounts(
        self, account_names: List[str], max_articles_per_account: int = 10
    ) -> List[ArticleSchema]:
        """批量抓取多个公众号的文章"""
        all_articles = []
        for account in account_names:
            try:
                articles = await self.search_by_account(account, max_articles_per_account)
                all_articles.extend(articles)
                await self.delay()
            except Exception as e:
                print(f"抓取公众号 '{account}' 失败: {e}")
                continue
        return all_articles
