"""通知器基类"""

from abc import ABC, abstractmethod
from typing import List

from ..storage.models import Article, ArticleSchema


class BaseNotifier(ABC):
    """通知器基类"""

    @abstractmethod
    async def send_article(self, article: Article, ai_summary: str = "") -> bool:
        """发送单篇文章通知

        Args:
            article: 文章对象
            ai_summary: AI 生成的摘要

        Returns:
            是否发送成功
        """
        pass

    @abstractmethod
    async def send_digest(self, articles: List[Article], title: str = "") -> bool:
        """发送文章摘要

        Args:
            articles: 文章列表
            title: 摘要标题

        Returns:
            是否发送成功
        """
        pass

    @abstractmethod
    async def send_text(self, text: str) -> bool:
        """发送纯文本消息

        Args:
            text: 消息文本

        Returns:
            是否发送成功
        """
        pass
