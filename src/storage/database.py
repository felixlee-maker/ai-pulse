"""数据库操作模块"""

import hashlib
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base, Article, ArticleSchema


class Database:
    """数据库操作类"""

    def __init__(self, db_url: str = "sqlite:///data/articles.db"):
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self._migrate_add_domain()
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _migrate_add_domain(self):
        """为旧数据库添加 domain 列"""
        from sqlalchemy import inspect, text
        inspector = inspect(self.engine)
        columns = [c["name"] for c in inspector.get_columns("articles")]
        if "domain" not in columns:
            with self.engine.connect() as conn:
                conn.execute(text("ALTER TABLE articles ADD COLUMN domain VARCHAR(50) DEFAULT 'ai'"))
                conn.commit()

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    @staticmethod
    def generate_article_id(url: str) -> str:
        """根据 URL 生成唯一 ID"""
        return hashlib.md5(url.encode()).hexdigest()

    def article_exists(self, url: str) -> bool:
        """检查文章是否已存在"""
        article_id = self.generate_article_id(url)
        with self.get_session() as session:
            return session.query(Article).filter(Article.id == article_id).first() is not None

    def save_article(self, article: ArticleSchema) -> Optional[Article]:
        """保存文章到数据库"""
        article_id = self.generate_article_id(article.url)

        with self.get_session() as session:
            # 检查是否已存在
            existing = session.query(Article).filter(Article.id == article_id).first()
            if existing:
                return None  # 已存在，跳过

            db_article = Article(
                id=article_id,
                title=article.title,
                url=article.url,
                author=article.author,
                summary=article.summary,
                content=article.content,
                publish_time=article.publish_time,
                crawl_time=article.crawl_time,
                domain=article.domain,
                relevance_score=article.relevance_score,
                ai_summary=article.ai_summary,
                is_relevant=article.is_relevant,
                notified=article.notified,
                notified_at=article.notified_at,
            )
            session.add(db_article)
            session.commit()
            session.refresh(db_article)
            return db_article

    def save_articles(self, articles: List[ArticleSchema]) -> List[Article]:
        """批量保存文章"""
        saved = []
        for article in articles:
            result = self.save_article(article)
            if result:
                saved.append(result)
        return saved

    def get_unnotified_articles(self, relevant_only: bool = True) -> List[Article]:
        """获取未通知的文章"""
        with self.get_session() as session:
            query = session.query(Article).filter(Article.notified == False)
            if relevant_only:
                query = query.filter(Article.is_relevant == True)
            return query.order_by(Article.crawl_time.desc()).all()

    def mark_as_notified(self, article_ids: List[str]) -> None:
        """标记文章为已通知"""
        with self.get_session() as session:
            session.query(Article).filter(Article.id.in_(article_ids)).update(
                {"notified": True, "notified_at": datetime.utcnow()},
                synchronize_session=False,
            )
            session.commit()

    def update_article_relevance(
        self, article_id: str, relevance_score: float, ai_summary: str, is_relevant: bool
    ) -> None:
        """更新文章的 AI 相关性评分"""
        with self.get_session() as session:
            session.query(Article).filter(Article.id == article_id).update(
                {
                    "relevance_score": relevance_score,
                    "ai_summary": ai_summary,
                    "is_relevant": is_relevant,
                },
                synchronize_session=False,
            )
            session.commit()

    def get_recent_articles(self, hours: int = 24, relevant_only: bool = False) -> List[Article]:
        """获取最近的文章"""
        since = datetime.utcnow() - timedelta(hours=hours)
        with self.get_session() as session:
            query = session.query(Article).filter(Article.crawl_time >= since)
            if relevant_only:
                query = query.filter(Article.is_relevant == True)
            return query.order_by(Article.crawl_time.desc()).all()

    def cleanup_old_articles(self, retention_days: int = 30) -> int:
        """清理旧文章"""
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        with self.get_session() as session:
            deleted = session.query(Article).filter(Article.crawl_time < cutoff).delete()
            session.commit()
            return deleted

    def get_article_by_url(self, url: str) -> Optional[Article]:
        """根据 URL 获取文章"""
        article_id = self.generate_article_id(url)
        with self.get_session() as session:
            return session.query(Article).filter(Article.id == article_id).first()

    def get_statistics(self) -> dict:
        """获取统计信息"""
        with self.get_session() as session:
            total = session.query(Article).count()
            relevant = session.query(Article).filter(Article.is_relevant == True).count()
            notified = session.query(Article).filter(Article.notified == True).count()
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = session.query(Article).filter(Article.crawl_time >= today).count()

            return {
                "total_articles": total,
                "relevant_articles": relevant,
                "notified_articles": notified,
                "today_articles": today_count,
            }
