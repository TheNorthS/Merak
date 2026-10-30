"""
专利工作流工具

Agent 可调用的专利相关工具：
- patent_search: 专利检索（Google Patents / Espacenet）
- claims_generator: 权利要求生成辅助
- prior_art_analyzer: 前引技术分析
- patent_template: 专利文档模板
"""

import re
from typing import Optional
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class PatentResult:
    patent_id: str
    title: str
    abstract: str
    applicant: str
    filing_date: str
    publication_date: str
    claims_count: int = 0
    url: str = ""
    relevance_score: float = 0.0


@dataclass
class PriorArtAnalysis:
    query: str
    patents_found: list[PatentResult] = field(default_factory=list)
    overlap_summary: str = ""
    novelty_assessment: str = ""
    suggested_differentiation: list[str] = field(default_factory=list)


class PatentTools:
    """专利工作流工具集"""

    async def search_patents(
        self,
        query: str,
        max_results: int = 20,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[PatentResult]:
        """搜索专利（Google Patents Public API）"""
        try:
            import httpx
        except ImportError:
            raise RuntimeError("pip install httpx")

        # 使用 Google Patents Public Datasets (BigQuery public) 的简化搜索
        # 实际使用 Espacenet Open Patent Services 或 Google Scholar Patents
        url = "https://serpapi.com/search"
        api_key = __import__('os').environ.get("SERPAPI_KEY", "")

        if api_key:
            # 使用 SerpAPI Google Patents
            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": api_key,
                "num": min(max_results, 20),
            }
            if date_from:
                params["after"] = f"filing_date:{date_from}"
            if date_to:
                params["before"] = f"filing_date:{date_to}"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    raise RuntimeError(f"SerpAPI patent search failed: HTTP {resp.status_code} {resp.text[:300]}")
                data = resp.json()
                results = []
                for item in data.get("organic_results", []):
                    results.append(PatentResult(
                        patent_id=item.get("patent_id", ""),
                        title=item.get("title", ""),
                        abstract=item.get("snippet", ""),
                        applicant=item.get("assignee", ""),
                        filing_date=item.get("filing_date", ""),
                        publication_date=item.get("publication_date", ""),
                        url=item.get("pdf", "") or item.get("link", ""),
                    ))
                return results

        # Fallback: 使用 Espacenet Open Patent Services (OPS) — 免费但需注册
        ops_key = __import__('os').environ.get("EPO_OPS_KEY", "")
        ops_secret = __import__('os').environ.get("EPO_OPS_SECRET", "")

        if ops_key and ops_secret:
            return await self._search_espacenet(
                query, max_results, ops_key, ops_secret, date_from=date_from, date_to=date_to
            )

        # 无 API key 时返回空（提示用户配置）
        raise RuntimeError(
            "No patent search API configured. Set and verify SERPAPI_KEY or EPO_OPS_KEY/EPO_OPS_SECRET."
        )

    async def _search_espacenet(
        self,
        query: str,
        max_results: int,
        key: str,
        secret: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[PatentResult]:
        """Espacenet Open Patent Services 搜索"""
        import httpx
        import base64

        # OAuth2 获取 token
        auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                "https://ops.epo.org/3.2/auth/accesstoken",
                headers={"Authorization": f"Basic {auth}"},
                data={"grant_type": "client_credentials"},
            )
            if token_resp.status_code != 200:
                logger.error("EPO OPS auth failed", status=token_resp.status_code)
                return []

            access_token = token_resp.json()["access_token"]

            # 搜索
            cql = f'ta="{query}"'
            if date_from:
                cql += f' and pd >= "{date_from.replace("-", "")}"'
            if date_to:
                cql += f' and pd <= "{date_to.replace("-", "")}"'
            search_resp = await client.get(
                "https://ops.epo.org/3.2/rest-services/published-data/search",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                params={"q": cql, "Range": f"1-{min(max_results, 25)}"},
            )

            results = []
            if search_resp.status_code == 200:
                data = search_resp.json()
                entries = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {}).get("ops:search-result", {}).get("ops:publication-reference", [])
                if isinstance(entries, dict):
                    entries = [entries]

                for entry in entries[:max_results]:
                    doc_id = entry.get("document-id", {})
                    results.append(PatentResult(
                        patent_id=f"{doc_id.get('country', {}).get('$', '')}{doc_id.get('doc-number', {}).get('$', '')}",
                        title="",  # 需要额外 API 调用获取
                        abstract="",
                        applicant="",
                        filing_date="",
                        publication_date="",
                        url=f"https://worldwide.espacenet.com/patent/search?q={doc_id.get('doc-number', {}).get('$', '')}",
                    ))

            if search_resp.status_code != 200:
                raise RuntimeError(
                    f"EPO OPS patent search failed: HTTP {search_resp.status_code} {search_resp.text[:300]}"
                )
            return results

    async def analyze_prior_art(
        self,
        invention_description: str,
        claims: list[str],
        search_results: Optional[list[PatentResult]] = None,
    ) -> PriorArtAnalysis:
        """分析前引技术"""
        # 如果没有提供搜索结果，先搜索
        if not search_results:
            search_results = await self.search_patents(invention_description, max_results=15)

        analysis = PriorArtAnalysis(
            query=invention_description,
            patents_found=search_results,
        )

        if not search_results:
            analysis.novelty_assessment = "No prior art found in patent databases. This may indicate novelty or insufficient search coverage."
            return analysis

        # 基于关键词重叠的简单评估（完整版应使用 LLM）
        invention_terms = set(re.findall(r'\b\w{4,}\b', invention_description.lower()))

        overlaps = []
        for patent in search_results:
            patent_terms = set(re.findall(r'\b\w{4,}\b', (patent.title + " " + patent.abstract).lower()))
            overlap = invention_terms & patent_terms
            if overlap:
                score = len(overlap) / max(len(invention_terms), 1)
                patent.relevance_score = round(score, 3)
                if score > 0.3:
                    overlaps.append(f"- {patent.patent_id}: {patent.title} (overlap: {score:.0%})")

        analysis.overlap_summary = "\n".join(overlaps[:10]) if overlaps else "Low keyword overlap with found patents."

        # 新颖性初步评估
        max_score = max((p.relevance_score for p in search_results), default=0)
        if max_score > 0.6:
            analysis.novelty_assessment = "HIGH OVERLAP: Several patents show significant similarity. Careful differentiation needed."
        elif max_score > 0.3:
            analysis.novelty_assessment = "MODERATE OVERLAP: Some related patents exist. Focus differentiation on specific claims."
        else:
            analysis.novelty_assessment = "LOW OVERLAP: No highly similar patents found. Novelty appears strong."

        # 差异化建议
        analysis.suggested_differentiation = [
            "Focus on specific technical implementation details",
            "Emphasize unique combination of known techniques",
            "Highlight specific performance improvements",
            "Define narrow, defensible independent claims",
        ]

        return analysis

    def generate_claims_template(
        self,
        invention_title: str,
        key_components: list[str],
        method_steps: list[str],
    ) -> str:
        """生成权利要求书模板"""
        claims = []

        # 独立权利要求 1（装置）
        components_text = ";\n    ".join(f"({chr(97+i)}) {c}" for i, c in enumerate(key_components))
        claims.append(f"""1. A system for {invention_title.lower()}, comprising:
    {components_text}.""")

        # 从属权利要求（装置细化）
        for i, comp in enumerate(key_components[:3], start=2):
            claims.append(f"{i}. The system of claim 1, wherein the {comp.split(',')[0].lower()} is configured to [specific detail].")

        # 独立权利要求（方法）
        next_num = len(key_components[:3]) + 2
        steps_text = ";\n    ".join(f"({chr(97+i)}) {s}" for i, s in enumerate(method_steps))
        claims.append(f"""{next_num}. A method for {invention_title.lower()}, comprising the steps of:
    {steps_text}.""")

        # 从属权利要求（方法细化）
        for i, step in enumerate(method_steps[:3], start=next_num + 1):
            claims.append(f"{i}. The method of claim {next_num}, wherein step ({chr(97 + method_steps.index(step))}) further comprises [specific detail].")

        return "\n\n".join(claims)

    def generate_patent_document_template(
        self,
        title: str,
        inventors: list[str],
        abstract: str = "",
    ) -> str:
        """生成完整专利文档模板"""
        inventors_text = "\n".join(f"- {inv}" for inv in inventors)

        return f"""# Patent Application

## Title of Invention
{title}

## Inventors
{inventors_text}

## Technical Field
[Describe the general technical field]

## Background of the Invention
[Describe the problem and existing solutions]

## Summary of the Invention
[Brief description of the invention]

### Abstract
{abstract or "[Provide a 150-word abstract]"}

## Brief Description of the Drawings
- FIG. 1 is a [description]
- FIG. 2 is a [description]

## Detailed Description of Preferred Embodiments

### System Overview
[Detailed system description with reference to figures]

### Method Steps
[Detailed method description]

### Implementation Details
[Specific implementation details]

## Claims
[See claims_generator output]

---
*Note: This is a template. Consult a patent attorney before filing.*
"""


# 全局实例
patent_tools = PatentTools()
