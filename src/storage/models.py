"""数据模型定义"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Text, DateTime, Float, Boolean, Integer
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel, Field

Base = declarative_base()


class Article(Base):
    """文章数据库模型"""

    __tablename__ = "articles"

    id = Column(String(64), primary_key=True)  # MD5 hash of url
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    author = Column(String(200))  # 公众号名称
    summary = Column(Text)  # 文章摘要
    content = Column(Text)  # 文章内容（可选）
    publish_time = Column(DateTime)  # 发布时间
    crawl_time = Column(DateTime, default=datetime.utcnow)  # 抓取时间

    # 领域分类
    domain = Column(String(50), default="ai")  # frontend / ai / devops

    # AI 过滤相关
    relevance_score = Column(Float, default=0.0)  # AI 相关性评分
    ai_summary = Column(Text)  # AI 生成的摘要
    is_relevant = Column(Boolean, default=False)  # 是否相关

    # 通知状态
    notified = Column(Boolean, default=False)  # 是否已通知
    notified_at = Column(DateTime)  # 通知时间

    def __repr__(self):
        return f"<Article(title='{self.title[:30]}...', author='{self.author}')>"


class ArticleSchema(BaseModel):
    """文章 Pydantic 模型（用于数据验证和传输）"""

    id: Optional[str] = None
    title: str
    url: str
    author: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    publish_time: Optional[datetime] = None
    crawl_time: datetime = Field(default_factory=datetime.utcnow)
    domain: str = "ai"
    relevance_score: float = 0.0
    ai_summary: Optional[str] = None
    is_relevant: bool = False
    notified: bool = False
    notified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountSchema(BaseModel):
    """公众号账号模型"""

    name: str
    id: str
    category: Optional[str] = None
    priority: str = "medium"  # high, medium, low
