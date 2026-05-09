"""邮件通知模块"""

import os
import ssl
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib

from .base import BaseNotifier
from ..storage.models import Article


# 定义北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))


class EmailNotifier(BaseNotifier):
    """邮件通知器

    使用 SMTP 发送邮件通知
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        to_address: Optional[str] = None,
    ):
        """
        Args:
            smtp_host: SMTP服务器地址
            smtp_port: SMTP端口
            smtp_user: SMTP用户名（发件邮箱）
            smtp_password: SMTP密码（应用专用密码）
            to_address: 收件人邮箱
        """
        self.smtp_host = smtp_host or os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(smtp_port or os.getenv("EMAIL_SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("EMAIL_SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("EMAIL_SMTP_PASSWORD")
        self.to_address = to_address or os.getenv("EMAIL_TO")

        if not self.smtp_user or not self.smtp_password:
            raise ValueError("EMAIL_SMTP_USER 或 EMAIL_SMTP_PASSWORD 未配置")
        if not self.to_address:
            raise ValueError("EMAIL_TO 未配置")

    async def _send_email(self, subject: str, html_content: str) -> bool:
        """发送邮件

        Args:
            subject: 邮件主题
            html_content: HTML格式的邮件内容

        Returns:
            是否发送成功
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = self.to_address

            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            # 创建 SSL 上下文
            context = ssl.create_default_context()

            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
                tls_context=context,
            )
            return True
        except Exception as e:
            print(f"邮件发送失败: {e}")
            return False

    def _build_article_html(self, article: Article, index: int, ai_summary: str = "") -> str:
        """构建单篇文章的HTML"""
        summary = ai_summary or article.summary or ""
        if len(summary) > 200:
            summary = summary[:200] + "..."

        # 格式化时间
        pub_time = ""
        if article.publish_time:
            pub_time = article.publish_time.strftime("%m-%d %H:%M")

        return f"""
        <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #e0e0e0; border-radius: 8px; background: #fafafa;">
            <div style="font-size: 16px; font-weight: bold; margin-bottom: 8px;">
                <a href="{article.url}" style="color: #1a73e8; text-decoration: none;">
                    {index}. {article.title}
                </a>
            </div>
            <div style="font-size: 13px; color: #666; margin-bottom: 8px;">
                {article.author or ''} · {pub_time}
            </div>
            <div style="font-size: 14px; color: #333; line-height: 1.6;">
                {summary}
            </div>
        </div>
        """

    async def send_article(self, article: Article, ai_summary: str = "") -> bool:
        """发送单篇文章通知"""
        html = self._build_article_html(article, 1, ai_summary)
        subject = f"[AI资讯] {article.title}"
        return await self._send_email(subject, html)

    async def send_digest(
        self,
        articles: List[Article],
        title: str = "",
        ai_summaries: Optional[dict] = None,
    ) -> bool:
        """发送文章摘要

        Args:
            articles: 文章列表
            title: 摘要标题
            ai_summaries: 文章ID到AI摘要的映射

        Returns:
            是否发送成功
        """
        if not articles:
            return True

        ai_summaries = ai_summaries or {}
        beijing_now = datetime.now(BEIJING_TZ)
        date_str = beijing_now.strftime("%Y-%m-%d")

        subject = title or f"AI 资讯日报 · {date_str}"

        # 构建HTML内容
        articles_html = ""
        for i, article in enumerate(articles, 1):
            summary = ai_summaries.get(article.id, "")
            articles_html += self._build_article_html(article, i, summary)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; background: #fff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="font-size: 24px; color: #333; margin-bottom: 5px;">{subject}</h1>
                <p style="font-size: 14px; color: #666;">共 {len(articles)} 篇文章</p>
            </div>

            {articles_html}

            <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0;">
                <p style="font-size: 12px; color: #999;">
                    由 AI-Pulse 自动生成 · {beijing_now.strftime("%Y-%m-%d %H:%M")}
                </p>
            </div>
        </body>
        </html>
        """

        return await self._send_email(subject, html_content)

    async def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        html = f"<p>{text}</p>"
        return await self._send_email("AI-Pulse 通知", html)

    async def send_error(self, error: str) -> bool:
        """发送错误通知"""
        html = f"""
        <div style="padding: 20px; background: #fff3f3; border: 1px solid #ff4444; border-radius: 8px;">
            <h3 style="color: #cc0000; margin-bottom: 10px;">AI-Pulse 运行错误</h3>
            <p style="color: #333;">{error}</p>
        </div>
        """
        return await self._send_email("[AI-Pulse] 错误通知", html)
