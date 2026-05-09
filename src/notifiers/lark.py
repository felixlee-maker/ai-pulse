"""飞书(Lark)通知模块"""

import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import httpx

from .base import BaseNotifier
from ..storage.models import Article


# 定义北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))


class LarkNotifier(BaseNotifier):
    """飞书 Webhook 通知器

    使用飞书机器人 Webhook 发送消息
    文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """
    DEFAULT_TEXT_MAX_BYTES = 3800
    DEFAULT_CARD_MAX_BYTES = 3200
    DEFAULT_CARD_MAX_ITEMS = 12
    TITLE_MAX_BYTES = 120
    AUTHOR_MAX_BYTES = 40
    CARD_RESERVED_BYTES = 200

    def __init__(self, webhook_url: Optional[str] = None):
        """
        Args:
            webhook_url: 飞书机器人 Webhook URL
        """
        self.webhook_url = webhook_url or os.getenv("LARK_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("LARK_WEBHOOK_URL 未配置")
        self.text_max_bytes = self._get_int_env(
            "LARK_TEXT_MAX_BYTES",
            self.DEFAULT_TEXT_MAX_BYTES,
            minimum=200,
        )
        self.card_max_bytes = self._get_int_env(
            "LARK_CARD_MAX_BYTES",
            self.DEFAULT_CARD_MAX_BYTES,
            minimum=500,
        )
        self.card_max_items = self._get_int_env(
            "LARK_CARD_MAX_ITEMS",
            self.DEFAULT_CARD_MAX_ITEMS,
            minimum=1,
        )
        self.title_max_bytes = self.TITLE_MAX_BYTES
        self.author_max_bytes = self.AUTHOR_MAX_BYTES

    @staticmethod
    def _get_int_env(key: str, default: int, minimum: int = 1) -> int:
        value = os.getenv(key)
        if value is None or value == "":
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(parsed, minimum)

    @staticmethod
    def _text_len(text: str) -> int:
        return len(text.encode("utf-8"))

    def _truncate_text(self, text: str, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        if self._text_len(text) <= max_bytes:
            return text
        if max_bytes <= 3:
            return text[:max_bytes]
        encoded = text.encode("utf-8")[: max_bytes - 3]
        truncated = encoded.decode("utf-8", errors="ignore")
        return f"{truncated}..."

    def _split_by_bytes(self, text: str, max_bytes: int) -> List[str]:
        if max_bytes <= 0:
            return [text]
        encoded = text.encode("utf-8")
        chunks: List[str] = []
        start = 0
        while start < len(encoded):
            end = min(start + max_bytes, len(encoded))
            piece = encoded[start:end].decode("utf-8", errors="ignore")
            if not piece:
                start += 1
                continue
            chunks.append(piece)
            start += len(piece.encode("utf-8"))
        return chunks or [text]

    def _split_text(self, text: str, max_bytes: int) -> List[str]:
        if self._text_len(text) <= max_bytes:
            return [text]
        chunks: List[str] = []
        current = ""
        for block in text.split("\n\n"):
            candidate = block if not current else f"{current}\n\n{block}"
            if self._text_len(candidate) <= max_bytes:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            if self._text_len(block) <= max_bytes:
                current = block
            else:
                chunks.extend(self._split_by_bytes(block, max_bytes))
        if current:
            chunks.append(current)
        return chunks

    def _format_article_line(
        self,
        article: Article,
        index: int,
        max_bytes: Optional[int] = None,
    ) -> str:
        title = (article.title or "").replace("\n", " ").strip()
        source = (article.author or "未知").replace("\n", " ").strip()
        source = self._truncate_text(source, self.author_max_bytes)
        # score = f" ({article.relevance_score:.0%})" if article.relevance_score else ""
        prefix = f"**{index}.** ["
        suffix = f"]({article.url})【📰 {source}】"
        title_budget = self.title_max_bytes
        if max_bytes is not None:
            title_budget = max_bytes - self._text_len(prefix + suffix)
            # if title_budget < 3:
            #     suffix = f"]({article.url})"
            #     title_budget = max_bytes - self._text_len(prefix + suffix)
            title_budget = max(3, min(self.title_max_bytes, title_budget))
        title = self._truncate_text(title, title_budget)
        return f"{prefix}{title}{suffix}"

    def _build_digest_cards(self, articles: List[Article], title: str) -> List[dict]:
        if not articles:
            return []
        max_bytes = max(self.card_max_bytes - self.CARD_RESERVED_BYTES, 200)
        chunks: List[List[str]] = []
        current: List[str] = []
        current_bytes = 0
        for index, article in enumerate(articles, 1):
            line = self._format_article_line(article, index, max_bytes=max_bytes)
            line_bytes = self._text_len(line)
            if current and (
                len(current) >= self.card_max_items
                or current_bytes + line_bytes > max_bytes
            ):
                chunks.append(current)
                current = []
                current_bytes = 0
            current.append(line)
            current_bytes += line_bytes
        if current:
            chunks.append(current)
        total_pages = len(chunks)
        return [
            self._build_digest_card(chunk, title, len(articles), page, total_pages)
            for page, chunk in enumerate(chunks, 1)
        ]

    async def _send_request(self, payload: dict) -> bool:
        """发送请求到飞书

        Args:
            payload: 请求体

        Returns:
            是否成功
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )
                result = response.json()
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    return True
                else:
                    print(f"飞书发送失败: {result}")
                    return False
        except Exception as e:
            print(f"飞书请求异常: {e}")
            return False

    async def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        if not text:
            return True
        for chunk in self._split_text(text, self.text_max_bytes):
            payload = {"msg_type": "text", "content": {"text": chunk}}
            if not await self._send_request(payload):
                return False
        return True

    async def send_article(self, article: Article, ai_summary: str = "") -> bool:
        """发送单篇文章通知（富文本卡片）"""
        # 构建交互式卡片
        card = self._build_article_card(article, ai_summary)
        payload = {"msg_type": "interactive", "card": card}
        return await self._send_request(payload)

    async def send_digest(self, articles: List[Article], title: str = "") -> bool:
        """发送文章摘要（多篇文章合并）"""
        if not articles:
            return True

        if not title:
            title = f"AI Pulse 日报 - {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}"

        cards = self._build_digest_cards(articles, title)
        for card in cards:
            payload = {"msg_type": "interactive", "card": card}
            if not await self._send_request(payload):
                return False
        return True

    def _build_article_card(self, article: Article, ai_summary: str = "") -> dict:
        """构建单篇文章卡片"""
        summary = ai_summary or article.summary or ""
        if len(summary) > 200:
            summary = summary[:200] + "..."
        title = (article.title or "").replace("\n", " ").strip()
        title = self._truncate_text(title, self.title_max_bytes)
        author = (article.author or "未知").replace("\n", " ").strip()
        author = self._truncate_text(author, self.author_max_bytes)

        publish_time = ""
        if article.publish_time:
            # 转换为北京时间
            dt = article.publish_time
            if dt.tzinfo is None:
                # 假设无时区时间为 UTC
                dt = dt.replace(tzinfo=timezone.utc)
            dt_bj = dt.astimezone(BEIJING_TZ)
            publish_time = dt_bj.strftime("%Y-%m-%d %H:%M")

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**来源**: {author}\n**时间**: {publish_time}",
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": summary},
                },
            ],
        }

        # 添加相关性评分（如果有）
        if article.relevance_score and article.relevance_score > 0:
            score_text = f"**AI 相关性**: {article.relevance_score:.0%}"
            card["elements"].append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": score_text},
                }
            )

        # 添加阅读按钮
        card["elements"].append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "阅读原文"},
                        "url": article.url,
                        "type": "primary",
                    }
                ],
            }
        )

        return card

    def _build_digest_card(
        self,
        article_lines: List[str],
        title: str,
        total_articles: int,
        page: int = 1,
        total_pages: int = 1,
    ) -> dict:
        """构建文章摘要卡片"""
        page_suffix = f" ({page}/{total_pages})" if total_pages > 1 else ""
        summary_line = f"共 **{total_articles}** 篇 AI 相关文章"
        if total_pages > 1:
            summary_line = f"{summary_line} · 第 {page}/{total_pages} 页"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{title}{page_suffix}"},
                "template": "turquoise",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": summary_line,
                    },
                },
                {"tag": "hr"},
            ],
        }

        # 添加文章列表
        for article_line in article_lines:
            card["elements"].append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": article_line},
                }
            )

        # 添加底部时间戳
        card["elements"].append({"tag": "hr"})
        card["elements"].append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"AI Pulse · {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M')}",
                    }
                ],
            }
        )

        return card

    async def send_error(self, error_message: str) -> bool:
        """发送错误通知"""
        if not error_message:
            error_message = "未知错误"
        max_bytes = max(self.card_max_bytes - self.CARD_RESERVED_BYTES, 200)
        chunks = self._split_text(error_message, max_bytes)
        total_pages = len(chunks)
        for page, chunk in enumerate(chunks, 1):
            page_suffix = f" ({page}/{total_pages})" if total_pages > 1 else ""
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"AI Pulse 运行错误{page_suffix}"},
                    "template": "red",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"```\n{chunk}\n```"},
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"时间: {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
                            }
                        ],
                    },
                ],
            }
            payload = {"msg_type": "interactive", "card": card}
            if not await self._send_request(payload):
                return False
        return True

    async def send_statistics(self, stats: dict) -> bool:
        """发送统计信息"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "AI Pulse 运行统计"},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**总文章数**\n{stats.get('total_articles', 0)}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**相关文章**\n{stats.get('relevant_articles', 0)}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**今日新增**\n{stats.get('today_articles', 0)}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**已通知**\n{stats.get('notified_articles', 0)}",
                            },
                        },
                    ],
                },
            ],
        }
        payload = {"msg_type": "interactive", "card": card}
        return await self._send_request(payload)
