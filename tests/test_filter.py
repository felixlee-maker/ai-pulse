"""AI 过滤器测试"""

import pytest
from datetime import datetime
from src.storage.models import ArticleSchema
from src.processors.filter import AIFilter


class TestAIFilter:
    """AI 过滤器测试"""

    @pytest.fixture
    def filter_instance(self):
        """创建过滤器实例（无 API Key，仅关键词过滤）"""
        return AIFilter(
            api_key=None,
            keywords_include=["AI", "人工智能", "ChatGPT", "大模型"],
            keywords_exclude=["广告", "招聘"],
        )

    @pytest.fixture
    def ai_article(self):
        """AI 相关文章"""
        return ArticleSchema(
            title="ChatGPT 发布最新版本，性能大幅提升",
            url="https://example.com/chatgpt",
            author="AI前线",
            summary="OpenAI 今日发布 ChatGPT 最新版本，在推理能力方面有显著提升。",
        )

    @pytest.fixture
    def non_ai_article(self):
        """非 AI 相关文章"""
        return ArticleSchema(
            title="今日菜谱：红烧肉的做法",
            url="https://example.com/food",
            author="美食频道",
            summary="教你做出美味的红烧肉。",
        )

    @pytest.fixture
    def excluded_article(self):
        """应排除的文章"""
        return ArticleSchema(
            title="AI 工程师招聘启事",
            url="https://example.com/job",
            author="招聘网",
            summary="招聘 AI 工程师，待遇优厚。",
        )

    @pytest.mark.asyncio
    async def test_keyword_include(self, filter_instance, ai_article):
        """测试包含关键词匹配"""
        result = await filter_instance.analyze_article(ai_article)
        assert result.is_relevant is True
        assert result.relevance_score > 0.5

    @pytest.mark.asyncio
    async def test_keyword_exclude(self, filter_instance, excluded_article):
        """测试排除关键词"""
        result = await filter_instance.analyze_article(excluded_article)
        assert result.is_relevant is False
        assert "排除" in result.reason

    @pytest.mark.asyncio
    async def test_no_keyword_match(self, filter_instance, non_ai_article):
        """测试无关键词匹配"""
        result = await filter_instance.analyze_article(non_ai_article)
        assert result.is_relevant is False
        assert result.relevance_score < 0.5


class TestKeywordPrefilter:
    """关键词预过滤测试"""

    def test_prefilter_include(self):
        """测试包含关键词预过滤"""
        filter_instance = AIFilter(
            api_key=None,
            keywords_include=["AI", "机器学习"],
            keywords_exclude=[],
        )
        has_include, should_exclude = filter_instance._keyword_prefilter(
            "AI 技术分享", "这是一篇关于机器学习的文章"
        )
        assert has_include is True
        assert should_exclude is False

    def test_prefilter_exclude(self):
        """测试排除关键词预过滤"""
        filter_instance = AIFilter(
            api_key=None,
            keywords_include=["AI"],
            keywords_exclude=["广告"],
        )
        has_include, should_exclude = filter_instance._keyword_prefilter(
            "AI 课程广告", "限时优惠"
        )
        assert should_exclude is True
