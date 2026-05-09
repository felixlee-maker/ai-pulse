"""AI 智能过滤模块

支持两种 AI 后端:
1. OpenAI API (需要 OPENAI_API_KEY)
2. Claude Code 无头模式 (需要本地安装 claude CLI，使用 Max 订阅额度)
"""

import os
import re
import json
import asyncio
from typing import List, Tuple, Optional
from dataclasses import dataclass

from ..storage.models import ArticleSchema


@dataclass
class FilterResult:
    """过滤结果"""

    is_relevant: bool
    relevance_score: float
    ai_summary: str
    reason: str


DOMAIN_PROMPTS = {
    "ai": """你是一个 AI 领域文章分析专家。请严格判断文章是否与人工智能(AI)领域直接相关。

【高度相关 (0.9-1.0)】核心AI内容：
- 大语言模型：ChatGPT、Claude、Gemini、Llama、通义千问、文心一言等
- 生成式AI：Stable Diffusion、Midjourney、Sora、DALL-E等
- AI Agent、RAG、Prompt Engineering、向量数据库
- AI行业重大新闻：产品发布、融资、政策法规
- AI技术突破：新模型、新算法、新论文

【一般相关 (0.7-0.89)】AI相关技术：
- 机器学习、深度学习的具体应用
- NLP、计算机视觉的技术文章
- AI开发工具和框架使用教程
- AI伦理、安全、治理讨论

【边缘相关 (0.5-0.69)】仅部分涉及AI：
- 只是提及AI但主题是其他技术
- 泛泛而谈的AI趋势评论
- AI公司的非AI业务新闻

【不相关 (0-0.49)】需严格排除：
- 普通软件开发（Web、App、数据库）
- 云计算、DevOps（除非与AI结合）
- 数据分析、BI（非ML/AI方法）
- 网络安全（非AI安全）
- 区块链、元宇宙（非AI相关）
- 硬件评测（非AI芯片）
- 职场、招聘、广告软文""",

    "frontend": """你是一个 Web 前端领域文章分析专家。请判断文章是否与前端开发直接相关。

【高度相关 (0.9-1.0)】核心前端内容：
- 主流框架重大更新：React、Vue、Svelte、Angular、Next.js、Nuxt
- 新 CSS 规范 / Web API / 浏览器新特性
- TypeScript、Vite、Bun、Deno 重大发布
- ECMAScript / TC39 新提案
- 前端性能优化重大突破

【一般相关 (0.7-0.89)】前端相关技术：
- 前端框架使用教程和最佳实践
- 构建工具、包管理器更新
- 前端测试工具和方法
- Web 可访问性、国际化
- 前端开源项目趋势

【边缘相关 (0.5-0.69)】仅部分涉及前端：
- 全栈开发但前端部分有限
- 泛泛的技术趋势讨论
- 设计/UX（非前端技术）

【不相关 (0-0.49)】需严格排除：
- 后端开发（Java、Python 后端框架）
- 移动原生开发（Swift、Kotlin）
- AI/ML（除非与前端结合）
- DevOps、运维
- 职场、招聘、广告软文""",

    "devops": """你是一个开发工程化领域文章分析专家。请判断文章是否与 DevOps / 工具链 / 基础设施相关。

【高度相关 (0.9-1.0)】核心 DevOps 内容：
- Docker、Kubernetes 重大更新
- Rust、Go、Zig 语言新版本发布
- IDE / 编辑器重大更新：VS Code、Cursor、JetBrains
- CI/CD 工具重大发布
- 平台工程趋势和实践

【一般相关 (0.7-0.89)】DevOps 相关技术：
- 构建工具、Monorepo 方案
- 云原生技术和架构
- 系统设计和可扩展性
- 监控、可观测性工具
- 开发者工具和效率提升

【边缘相关 (0.5-0.69)】仅部分涉及 DevOps：
- 泛泛的工程管理讨论
- 通用编程语言更新（非工具链）
- 系统管理但非 DevOps

【不相关 (0-0.49)】需严格排除：
- 前端框架开发
- AI/ML（除非与 DevOps 结合）
- 产品管理、设计
- 职场、招聘、广告软文""",
}

SCORING_SUFFIX = """

【评分原则】
1. 严格评分：宁可漏判不可错判，只有真正核心内容才给0.9+
2. 标题为主：重点看标题，摘要作为辅助判断
3. 内容深度：深度技术文章 > 新闻资讯 > 泛泛评论

严格以 JSON 格式输出（不要包含其他文字）：
{
  "is_relevant": true/false,
  "relevance_score": 0.0-1.0,
  "summary": "一句话中文摘要",
  "reason": "简短判断理由"
}"""

# 保持向后兼容
SYSTEM_PROMPT = DOMAIN_PROMPTS["ai"] + SCORING_SUFFIX


def _get_system_prompt(domain: str = "ai") -> str:
    """根据领域获取系统提示词"""
    base = DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["ai"])
    return base + SCORING_SUFFIX


def _build_user_prompt(title: str, summary: str, domain: str = "ai") -> str:
    """构建用户提示词"""
    domain_labels = {
        "ai": "AI/人工智能",
        "frontend": "Web 前端开发",
        "devops": "开发工程化/DevOps",
    }
    label = domain_labels.get(domain, domain)
    return f"""请分析以下文章：

标题：{title}
摘要：{summary}

请判断这篇文章是否与{label}领域相关。严格以 JSON 格式输出。"""


def _parse_ai_response(response_text: str) -> dict:
    """解析 AI 返回的 JSON"""
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    try:
        json_match = re.search(r"\{[\s\S]*?\}", response_text)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass

    return {}


class ClaudeCodeBackend:
    """Claude Code 无头模式后端

    通过 `claude -p` 子进程调用 Claude，使用 Max 订阅额度，无需 API key。
    """

    def __init__(self, max_concurrency: int = 3, model: Optional[str] = None):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.model = model

    async def analyze(self, title: str, summary: str, domain: str = "ai") -> dict:
        """调用 claude -p 分析文章"""
        prompt = f"""{_get_system_prompt(domain)}

{_build_user_prompt(title, summary, domain)}"""

        async with self.semaphore:
            try:
                cmd = ["claude", "-p", "--output-format", "text"]
                if self.model:
                    cmd.extend(["--model", self.model])

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=60,
                )

                if proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    raise RuntimeError(f"claude 进程退出码 {proc.returncode}: {err_msg}")

                result_text = stdout.decode("utf-8", errors="replace").strip()
                return _parse_ai_response(result_text)

            except asyncio.TimeoutError:
                raise RuntimeError("claude 进程超时 (60s)")


class OpenAIBackend:
    """OpenAI API 后端（兼容 OpenAI 协议的任何服务）"""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        from openai import AsyncOpenAI

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def analyze(self, title: str, summary: str, domain: str = "ai") -> dict:
        """调用 OpenAI API 分析文章"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _get_system_prompt(domain)},
                {"role": "user", "content": _build_user_prompt(title, summary, domain)},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        result_text = response.choices[0].message.content
        return _parse_ai_response(result_text)


class AIFilter:
    """AI 智能过滤器

    支持 Claude Code 无头模式和 OpenAI API 两种后端。
    优先使用配置指定的后端，自动降级到关键词过滤。
    """

    def __init__(
        self,
        backend: str = "claude-code",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        relevance_threshold: float = 0.6,
        keywords_include: Optional[List[str]] = None,
        keywords_exclude: Optional[List[str]] = None,
        max_concurrency: int = 3,
    ):
        self.relevance_threshold = relevance_threshold
        self.keywords_include = keywords_include or []
        self.keywords_exclude = keywords_exclude or []
        self.backend_name = backend

        # 初始化 AI 后端
        self.backend = None
        if backend == "claude-code":
            self.backend = ClaudeCodeBackend(
                max_concurrency=max_concurrency,
                model=model,
            )
        elif backend == "openai":
            key = api_key or os.getenv("OPENAI_API_KEY")
            if key:
                self.backend = OpenAIBackend(
                    api_key=key,
                    base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                    model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                )

    def _keyword_prefilter(self, title: str, summary: str) -> Tuple[bool, bool]:
        """关键词预过滤

        Returns:
            (should_include, should_exclude): 是否包含关键词，是否应排除
        """
        text = f"{title} {summary}".lower()

        for keyword in self.keywords_exclude:
            if keyword.lower() in text:
                return False, True

        for keyword in self.keywords_include:
            if keyword.lower() in text:
                return True, False

        return False, False

    async def analyze_article(self, article: ArticleSchema) -> FilterResult:
        """分析单篇文章的相关性"""
        title = article.title
        summary = article.summary or ""

        has_include_keyword, should_exclude = self._keyword_prefilter(title, summary)

        if should_exclude:
            return FilterResult(
                is_relevant=False,
                relevance_score=0.0,
                ai_summary="",
                reason="包含排除关键词",
            )

        # 如果没有 AI 后端，只使用关键词过滤
        if not self.backend:
            return FilterResult(
                is_relevant=has_include_keyword,
                relevance_score=0.8 if has_include_keyword else 0.2,
                ai_summary=summary[:100] if summary else title,
                reason="关键词匹配" if has_include_keyword else "无关键词匹配",
            )

        # 使用 AI 后端进行深度分析
        try:
            domain = getattr(article, "domain", "ai") or "ai"
            result = await self.backend.analyze(title, summary, domain)

            return FilterResult(
                is_relevant=result.get("is_relevant", False)
                and result.get("relevance_score", 0) >= self.relevance_threshold,
                relevance_score=result.get("relevance_score", 0),
                ai_summary=result.get("summary", ""),
                reason=result.get("reason", ""),
            )

        except Exception as e:
            print(f"AI 分析失败 [{self.backend_name}]: {e}")
            return FilterResult(
                is_relevant=has_include_keyword,
                relevance_score=0.5 if has_include_keyword else 0.2,
                ai_summary=summary[:100] if summary else title,
                reason=f"AI 分析失败，降级到关键词过滤: {e}",
            )

    async def filter_articles(
        self, articles: List[ArticleSchema]
    ) -> List[Tuple[ArticleSchema, FilterResult]]:
        """批量过滤文章（并发处理）"""

        async def _process(article: ArticleSchema):
            result = await self.analyze_article(article)
            return (article, result)

        tasks = [_process(article) for article in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"文章处理异常: {r}")
                article = articles[i]
                summary = article.summary or ""
                final.append((article, FilterResult(
                    is_relevant=False,
                    relevance_score=0.0,
                    ai_summary=summary[:100] if summary else article.title,
                    reason=f"处理异常: {r}",
                )))
            else:
                final.append(r)
        return final

    async def get_relevant_articles(
        self, articles: List[ArticleSchema]
    ) -> List[Tuple[ArticleSchema, FilterResult]]:
        """获取相关文章"""
        all_results = await self.filter_articles(articles)
        return [(article, result) for article, result in all_results if result.is_relevant]
