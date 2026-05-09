"""每日结构化数据导出模块

每日执行后生成 JSON + Markdown 双格式报告，供其他 agent 分析使用。
使用当天全量相关文章数据，不受飞书推送条数限制。
支持按领域（frontend / ai / devops）分类输出。
"""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from ..storage.models import ArticleSchema


BEIJING_TZ = timezone(timedelta(hours=8))

DOMAIN_META = {
    "frontend": {"icon": "\U0001f5a5", "label": "Web 前端"},
    "ai": {"icon": "\U0001f916", "label": "AI / 机器学习"},
    "devops": {"icon": "\U0001f527", "label": "开发工程化"},
}

DOMAIN_ORDER = ["frontend", "ai", "devops"]


def _importance_emoji(score: float) -> str:
    if score >= 0.9:
        return "\U0001f534"
    if score >= 0.7:
        return "\U0001f7e1"
    return "\U0001f7e2"


class DailyReportExporter:
    """每日报告导出器"""

    def __init__(self, output_dir: str = "data/daily"):
        from pathlib import Path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        articles: List[ArticleSchema],
        stats: dict,
    ) -> dict:
        """导出当天全量相关文章为 JSON + Markdown"""
        now = datetime.now(BEIJING_TZ)
        date_str = now.strftime("%Y-%m-%d")

        sorted_articles = sorted(
            articles,
            key=lambda a: a.relevance_score or 0,
            reverse=True,
        )

        report_data = self._build_report_data(sorted_articles, stats, now, date_str)

        json_path = self.output_dir / f"{date_str}.json"
        json_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        md_path = self.output_dir / f"{date_str}.md"
        md_path.write_text(
            self._build_markdown(report_data),
            encoding="utf-8",
        )

        return {"json": str(json_path), "md": str(md_path)}

    def _group_by_domain(self, articles: list) -> Dict[str, list]:
        groups: Dict[str, list] = {}
        for a in articles:
            d = a.get("domain", "ai") if isinstance(a, dict) else getattr(a, "domain", "ai")
            groups.setdefault(d, []).append(a)
        return groups

    def _build_report_data(
        self,
        articles: List[ArticleSchema],
        stats: dict,
        now: datetime,
        date_str: str,
    ) -> dict:
        scores = [a.relevance_score for a in articles if a.relevance_score]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0

        source_counts: dict = {}
        for a in articles:
            src = a.author or "未知"
            source_counts[src] = source_counts.get(src, 0) + 1

        tiers = {"core (≥0.9)": 0, "general (0.7-0.89)": 0, "edge (0.5-0.69)": 0}
        for a in articles:
            s = a.relevance_score or 0
            if s >= 0.9:
                tiers["core (≥0.9)"] += 1
            elif s >= 0.7:
                tiers["general (0.7-0.89)"] += 1
            elif s >= 0.5:
                tiers["edge (0.5-0.69)"] += 1

        domain_counts: dict = {}
        for a in articles:
            d = getattr(a, "domain", "ai") or "ai"
            domain_counts[d] = domain_counts.get(d, 0) + 1

        return {
            "date": date_str,
            "generated_at": now.isoformat(),
            "stats": {
                "total_fetched": stats.get("fetched", 0),
                "after_dedup": stats.get("new", 0),
                "relevant": len(articles),
                "avg_score": avg_score,
                "by_source": source_counts,
                "by_tier": tiers,
                "by_domain": domain_counts,
            },
            "articles": [
                {
                    "title": a.title,
                    "url": a.url,
                    "source": a.author or "未知",
                    "domain": getattr(a, "domain", "ai") or "ai",
                    "relevance_score": a.relevance_score,
                    "ai_summary": a.ai_summary or "",
                    "published_at": a.publish_time.isoformat() if a.publish_time else None,
                }
                for a in articles
            ],
        }

    def _build_markdown(self, data: dict) -> str:
        s = data["stats"]
        date_str = data["date"]

        lines = [
            f"# \U0001f5d3 技术日报 — {date_str}",
            "",
        ]

        # 今日头条：取全局最高分文章
        all_articles = data["articles"]
        headlines = [a for a in all_articles if a["relevance_score"] >= 0.9][:2]
        if headlines:
            top = headlines[0]
            lines.append(f"> 今日一句话：{top['ai_summary'] or top['title']}")
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("\U0001f525 今日头条")
            lines.append("")
            for h in headlines:
                lines.append(f"**[{h['title']}]({h['url']})**")
                lines.append(f"来源：{h['source']} | 评分：{h['relevance_score']}")
                if h["ai_summary"]:
                    lines.append(f"> {h['ai_summary']}")
                lines.append("")
        else:
            lines.append("> 今天各领域以常规动态为主")
            lines.append("")

        lines.append("---")
        lines.append("")

        # 按领域输出表格
        grouped = self._group_by_domain(all_articles)
        for domain_key in DOMAIN_ORDER:
            domain_articles = grouped.get(domain_key, [])
            if not domain_articles:
                continue

            meta = DOMAIN_META.get(domain_key, {"icon": "\U0001f4cc", "label": domain_key})
            lines.append(f"## {meta['icon']} {meta['label']}")
            lines.append("")
            lines.append("| # | 标题 | 来源 | 摘要 | 重要度 |")
            lines.append("|---|------|------|------|--------|")

            for i, a in enumerate(domain_articles, 1):
                title_link = f"[{a['title']}]({a['url']})"
                summary = (a["ai_summary"] or "")[:80]
                emoji = _importance_emoji(a["relevance_score"])
                lines.append(f"| {i} | {title_link} | {a['source']} | {summary} | {emoji} |")

            lines.append("")
            lines.append("---")
            lines.append("")

        # 统计信息
        lines.append("## \U0001f4ca 统计")
        lines.append("")
        lines.append(f"- 抓取: {s['total_fetched']} | 去重后: {s['after_dedup']} | 相关: {s['relevant']} | 平均分: {s['avg_score']}")
        lines.append("")

        if s.get("by_domain"):
            lines.append("### 领域分布")
            lines.append("")
            for d, count in s["by_domain"].items():
                meta = DOMAIN_META.get(d, {"icon": "", "label": d})
                lines.append(f"- {meta['label']}: {count}")
            lines.append("")

        if s.get("by_tier"):
            lines.append("### 分数分布")
            lines.append("")
            for tier, count in s["by_tier"].items():
                lines.append(f"- {tier}: {count}")
            lines.append("")

        if s.get("by_source"):
            lines.append("### 来源分布")
            lines.append("")
            for src, count in sorted(s["by_source"].items(), key=lambda x: -x[1]):
                lines.append(f"- {src}: {count}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"_由 AI-Pulse 自动整理 | {date_str}_")

        return "\n".join(lines)
