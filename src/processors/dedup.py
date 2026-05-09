"""文章去重模块"""

import hashlib
from typing import List, Set
from datetime import datetime, timedelta

from ..storage.models import ArticleSchema
from ..storage.database import Database


class Deduplicator:
    """文章去重器"""

    def __init__(self, db: Database, window_hours: int = 48):
        """
        Args:
            db: 数据库实例
            window_hours: 去重窗口（小时）
        """
        self.db = db
        self.window_hours = window_hours
        self._seen_urls: Set[str] = set()
        self._seen_titles: Set[str] = set()

    def _normalize_title(self, title: str) -> str:
        """标准化标题用于比较"""
        # 移除空白和标点
        import re

        normalized = re.sub(r"[\s\u3000]+", "", title)  # 移除空白
        normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", normalized)  # 保留字母数字和中文
        return normalized.lower()

    def _title_hash(self, title: str) -> str:
        """计算标题哈希"""
        normalized = self._normalize_title(title)
        return hashlib.md5(normalized.encode()).hexdigest()

    def is_duplicate(self, article: ArticleSchema) -> bool:
        """检查文章是否重复

        Args:
            article: 文章

        Returns:
            是否重复
        """
        # 检查 URL 是否已存在
        if self.db.article_exists(article.url):
            return True

        # 检查本批次内是否重复
        if article.url in self._seen_urls:
            return True

        # 检查标题相似性（同一批次内）
        title_hash = self._title_hash(article.title)
        if title_hash in self._seen_titles:
            return True

        return False

    def mark_seen(self, article: ArticleSchema) -> None:
        """标记文章为已见"""
        self._seen_urls.add(article.url)
        self._seen_titles.add(self._title_hash(article.title))

    def deduplicate(self, articles: List[ArticleSchema]) -> List[ArticleSchema]:
        """去重文章列表

        Args:
            articles: 原始文章列表

        Returns:
            去重后的文章列表
        """
        unique_articles = []

        for article in articles:
            if not self.is_duplicate(article):
                self.mark_seen(article)
                unique_articles.append(article)

        return unique_articles

    def reset(self) -> None:
        """重置批次内的去重状态"""
        self._seen_urls.clear()
        self._seen_titles.clear()
