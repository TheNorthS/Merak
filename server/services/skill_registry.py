"""
MERAK 技能注册表 — 扫描、解析、索引

功能：
- 扫描 MERAK skills/ 目录
- 解析 SKILL.md 文件提取元数据
- 构建分类索引
- 全文搜索
- 技能依赖图
"""

import re
from fnmatch import fnmatchcase
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import structlog
from .artifact_contract import (
    declared_skill_artifact_contracts,
    declared_skill_outputs,
    validate_skill_artifact_contracts,
)

logger = structlog.get_logger()

RUNTIME_REVIEWER_SESSION_CONTRACT = """\
> **MERAK runtime reviewer contract (overrides imported identity wording):**
> Reviewer and Executor MAY use the same provider, concrete model, or model
> family. Reviewer independence means a fresh, context-isolated, read-only
> invocation over frozen primary artifacts with its own durable trace. Never
> reject, skip, downgrade, or withhold a verdict only because the model
> identities match. Historical instructions requiring different model
> identities or families are non-binding in the MERAK runtime.

"""


def normalize_skill_runtime_contract(content: str) -> str:
    """Attach the isolated-review policy to current native skill contracts.

    Unsupported transport identifiers are rejected, not translated into a
    different tool. Bundled skill sources already name the native API tools.
    """
    normalized = str(content or "")
    if re.search(r"mcp__codex__|\bCodex\s+MCP\b", normalized, re.IGNORECASE):
        raise ValueError("Unsupported reviewer transport; use reviewer_api or reviewer_api_reply")
    if normalized.strip() and RUNTIME_REVIEWER_SESSION_CONTRACT not in normalized:
        frontmatter = re.match(
            r"^---\s*\n.*?\n---\s*(?:\n|$)",
            normalized,
            re.DOTALL,
        )
        if frontmatter:
            split_at = frontmatter.end()
            normalized = (
                normalized[:split_at]
                + RUNTIME_REVIEWER_SESSION_CONTRACT
                + normalized[split_at:]
            )
        else:
            normalized = RUNTIME_REVIEWER_SESSION_CONTRACT + normalized
    return normalized


@dataclass
class SkillMetadata:
    """技能元数据"""
    id: str
    name: str
    category: str
    description: str
    trigger: str  # 触发命令 /skill-name
    effort_levels: list[str] = field(default_factory=lambda: ["lite", "balanced", "max", "beast"])
    assurance_levels: list[str] = field(default_factory=lambda: ["draft", "submission"])
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    artifact_contracts: dict[str, int] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # 依赖的其他技能
    tags: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    file_path: str = ""
    content_preview: str = ""  # 前 500 字符


# 技能分类规则
CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["research-pipeline", "idea-discovery", "experiment-bridge", "auto-review-loop",
      "paper-writing", "rebuttal", "resubmit-pipeline", "paper-talk",
      "research-refine-pipeline", "patent-pipeline", "dse-loop",
      "meta-optimize", "meta-apply", "idea-discovery-robot"], "Workflow Orchestrator"),
    (["research-lit", "arxiv", "semantic-scholar", "deepxiv", "exa-search",
      "openalex", "gemini-search", "alphaxiv", "comm-lit-review", "novelty-check"], "Literature & Search"),
    (["idea-creator", "research-refine", "experiment-plan", "ablation-planner",
      "formula-derivation", "domain-methodology", "statistical-analysis-plan",
      "data-quality-audit", "domain-validation", "ethics-governance"], "Ideation & Method"),
    (["run-experiment", "monitor-experiment", "analyze-results", "experiment-queue",
      "vast-gpu", "serverless-modal", "qzcli", "training-check", "system-profile"], "Experiments & Infra"),
    (["research-review", "experiment-audit", "result-to-claim", "paper-claim-audit",
      "citation-audit", "proof-checker", "kill-argument"], "Review & Audit"),
    (["paper-plan", "paper-write", "paper-figure", "figure-layout-director", "rich-svg-figure", "model-svg-figure", "figure-spec", "paper-illustration", "excalidraw-skill",
      "mermaid-diagram", "pixel-art", "paper-compile",
      "auto-paper-improvement-loop", "proof-writer", "writing-systems-papers",
      "grant-proposal"], "Paper Writing & Figures"),
    (["paper-slides", "slides-polish", "paper-poster-html", "paper-poster"], "Talks & Posters"),
    (["invention-structuring", "claims-drafting", "embodiment-description",
      "specification-writing", "figure-description", "prior-art-search",
      "patent-novelty-check", "patent-review"], "Patents"),
]


def categorize_skill(skill_name: str) -> str:
    """根据技能名称确定分类"""
    for names, category in CATEGORY_RULES:
        if skill_name in names:
            return category
    return "Other"


def _skill_frontmatter_contract(
    content: str, skill_name: str,
) -> tuple[list[str], dict[str, int], list[str]] | None:
    frontmatter = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    frontmatter_text = frontmatter.group(1) if frontmatter else ""
    tools_match = re.search(r"(?m)^allowed-tools:\s*(.+?)\s*$", frontmatter_text)
    allowed_tools = []
    if tools_match:
        allowed_tools = [
            re.sub(r"\(.*\)$", "", item.strip())
            for item in tools_match.group(1).split(",") if item.strip()
        ]
    try:
        output_files = declared_skill_outputs(frontmatter_text)
        artifact_contracts = declared_skill_artifact_contracts(frontmatter_text)
        validate_skill_artifact_contracts(output_files, artifact_contracts)
    except ValueError as error:
        logger.warning("Invalid skill artifact declaration", skill=skill_name, error=str(error))
        return None
    return output_files, artifact_contracts, list(dict.fromkeys(allowed_tools))


def parse_skill_md(skill_path: Path) -> Optional[SkillMetadata]:
    """解析 SKILL.md 文件提取元数据"""
    try:
        content = normalize_skill_runtime_contract(
            skill_path.read_text(encoding='utf-8')
        )
    except Exception:
        return None

    skill_name = skill_path.parent.name

    # 提取描述（第一个标题或第一段有意义的文字）
    description = ""
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and not stripped.startswith('---') and not stripped.startswith('```'):
            description = stripped[:300]
            break

    trigger = f"/{skill_name}"
    tags = []
    input_files = []
    depends_on = []
    contract = _skill_frontmatter_contract(content, skill_name)
    if contract is None:
        return None
    output_files, artifact_contracts, allowed_tools = contract

    # 寻找 input/output 相关内容
    input_match = re.findall(r'(?:input|reads?|requires?).*?[`"]([^`"]+)[`"]', content, re.IGNORECASE)
    if input_match:
        input_files = input_match[:5]

    # 寻找依赖的其他技能
    skill_refs = re.findall(r'/([a-z][\w-]+)', content)
    depends_on = [ref for ref in set(skill_refs) if ref != skill_name and len(ref) > 3][:10]

    # 提取标签（从内容中推断）
    if "gpu" in content.lower() or "cuda" in content.lower():
        tags.append("gpu")
    if "latex" in content.lower() or "tex" in content.lower():
        tags.append("latex")
    if "review" in content.lower():
        tags.append("review")
    if "experiment" in content.lower():
        tags.append("experiment")

    return SkillMetadata(
        id=skill_name,
        name=skill_name,
        category=categorize_skill(skill_name),
        description=description,
        trigger=trigger,
        input_files=input_files,
        output_files=output_files,
        artifact_contracts=artifact_contracts,
        depends_on=depends_on[:10],
        tags=tags,
        allowed_tools=list(dict.fromkeys(allowed_tools)),
        file_path=str(skill_path),
        content_preview=content[:500],
    )


class SkillRegistry:
    """MERAK 技能注册表"""

    def __init__(self):
        self._skills: dict[str, SkillMetadata] = {}
        self._by_category: dict[str, list[str]] = {}
        self._search_index: dict[str, set[str]] = {}  # token -> skill_ids

    def scan_directory(self, skills_dir: str | Path) -> int:
        """扫描技能目录并建立索引"""
        skills_path = Path(skills_dir)
        if not skills_path.exists():
            logger.warning("Skills directory not found", path=str(skills_path))
            return 0

        count = 0
        for skill_dir in sorted(skills_path.iterdir()):
            if not skill_dir.is_dir():
                continue
            # 跳过 shared-references 等非技能目录
            if (
                skill_dir.name.startswith('shared-')
                or skill_dir.name.startswith('.')
            ):
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            metadata = parse_skill_md(skill_file)
            if metadata:
                self._skills[metadata.id] = metadata
                count += 1

        # 构建分类索引
        self._build_category_index()
        # 构建搜索索引
        self._build_search_index()

        logger.info("Skill registry loaded", total=count, categories=len(self._by_category))
        return count

    def _build_category_index(self):
        """构建分类索引"""
        self._by_category.clear()
        for skill_id, skill in self._skills.items():
            if skill.category not in self._by_category:
                self._by_category[skill.category] = []
            self._by_category[skill.category].append(skill_id)

    def _build_search_index(self):
        """构建搜索索引（简单的倒排索引）"""
        self._search_index.clear()
        for skill_id, skill in self._skills.items():
            # 索引名称、描述、标签中的词
            tokens = set()
            tokens.update(skill.name.replace('-', ' ').split())
            tokens.update(skill.description.lower().split())
            tokens.update(skill.tags)
            tokens.add(skill.category.lower())

            for token in tokens:
                token = token.lower().strip('.,;:!?()[]{}')
                if len(token) >= 2:
                    if token not in self._search_index:
                        self._search_index[token] = set()
                    self._search_index[token].add(skill_id)

    # ==================== 查询接口 ====================

    def get_skill(self, skill_id: str) -> Optional[SkillMetadata]:
        """获取单个技能"""
        return self._skills.get(skill_id)

    def list_all(self) -> list[SkillMetadata]:
        """列出所有技能"""
        return sorted(self._skills.values(), key=lambda s: (s.category, s.name))

    def list_by_category(self, category: str) -> list[SkillMetadata]:
        """按分类列出"""
        skill_ids = self._by_category.get(category, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def get_categories(self) -> list[dict]:
        """获取所有分类及数量"""
        return [
            {"name": cat, "count": len(ids)}
            for cat, ids in sorted(self._by_category.items())
        ]

    def search(self, query: str, limit: int = 20) -> list[SkillMetadata]:
        """搜索技能"""
        query_tokens = query.lower().split()
        if not query_tokens:
            return []

        # 交集搜索
        result_ids: Optional[set] = None
        for token in query_tokens:
            matches = set()
            for index_token, skill_ids in self._search_index.items():
                if token in index_token:
                    matches.update(skill_ids)
            if result_ids is None:
                result_ids = matches
            else:
                result_ids &= matches

        if not result_ids:
            return []

        results = [self._skills[sid] for sid in result_ids if sid in self._skills]
        return sorted(results, key=lambda s: s.name)[:limit]

    def resolve_allowed_tools(
        self,
        skill_id: str,
        available_tools: list[str],
    ) -> list[str]:
        """Expand a skill's exact and wildcard tool declarations."""
        metadata = self.get_skill(skill_id.lstrip("/"))
        if not metadata or not metadata.allowed_tools:
            return []
        return [
            name
            for name in available_tools
            if any(fnmatchcase(name, pattern) for pattern in metadata.allowed_tools)
        ]

    def get_dependency_graph(self) -> dict:
        """获取技能依赖图（用于可视化）"""
        nodes = []
        edges = []

        for skill_id, skill in self._skills.items():
            nodes.append({
                "id": skill_id,
                "label": skill.name,
                "category": skill.category,
            })
            for dep in skill.depends_on:
                if dep in self._skills:
                    edges.append({
                        "source": skill_id,
                        "target": dep,
                    })

        return {"nodes": nodes, "edges": edges}

    def get_pipeline_definition(self, pipeline_name: str = "research-pipeline") -> list[dict]:
        """获取流水线定义（阶段序列）"""
        # MERAK 的核心流水线：W1 → W1.5 → W2 → W3
        pipelines = {
            "research-pipeline": [
                {"id": "W1", "skill": "idea-discovery", "name": "Idea Discovery"},
                {"id": "W1.5", "skill": "experiment-bridge", "name": "Experiment Bridge"},
                {"id": "W2", "skill": "auto-review-loop", "name": "Auto Review Loop"},
                {"id": "W3", "skill": "paper-writing", "name": "Paper Writing"},
            ],
            "paper-pipeline": [
                {"id": "P1", "skill": "paper-plan", "name": "Paper Plan"},
                {"id": "P2", "skill": "paper-write", "name": "Paper Write"},
                {"id": "P3", "skill": "paper-figure", "name": "Figures"},
                {"id": "P4", "skill": "paper-compile", "name": "Compile"},
                {"id": "P5", "skill": "auto-review-loop", "name": "Review Loop"},
            ],
            "patent-pipeline": [
                {"id": "T1", "skill": "invention-structuring", "name": "Structuring"},
                {"id": "T2", "skill": "prior-art-search", "name": "Prior Art"},
                {"id": "T3", "skill": "claims-drafting", "name": "Claims"},
                {"id": "T4", "skill": "specification-writing", "name": "Specification"},
            ],
        }
        return pipelines.get(pipeline_name, [])

    @property
    def total_skills(self) -> int:
        return len(self._skills)


# 全局实例
skill_registry = SkillRegistry()
