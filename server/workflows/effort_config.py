"""
Effort/Assurance 配置缩放器

根据 effort 级别动态调整 workflow 行为：
- lite:     搜索 12-15 篇，idea 4-6 个，审稿 1-2 轮
- balanced: 搜索 30-40 篇，idea 8-12 个，审稿 2-3 轮 (DEFAULT)
- max:      搜索 45-55 篇，idea 12-16 个，审稿 3-4 轮
- beast:    搜索 70-80 篇，idea 20-30 个，审稿 4+ 轮

assurance 控制审计严格度：
- draft:           审计 optional，不阻塞
- polished:        运行关键审计，FAIL/BLOCKED/ERROR 阻塞
- conference-ready: 提交前严格审计，WARN 也阻塞
- submission:      提交模式，WARN/FAIL/BLOCKED/ERROR 均阻塞
"""

from dataclasses import dataclass


@dataclass
class EffortConfig:
    """根据 effort 级别生成的配置参数"""
    papers_to_search: int
    ideas_to_generate: int
    pilot_experiments: int
    review_rounds: int
    max_agent_iterations: int
    search_depth: str  # "shallow" | "moderate" | "deep" | "exhaustive"
    code_review: bool
    figure_quality: str  # "draft" | "publication"


@dataclass
class AssuranceConfig:
    """根据 assurance 级别生成的配置"""
    audit_mandatory: bool
    audit_blocking: bool  # FAIL/BLOCKED/ERROR 是否阻塞
    citation_verify: bool
    proof_check: bool
    warn_blocking: bool = False


EFFORT_CONFIGS = {
    "lite": EffortConfig(
        papers_to_search=15,
        ideas_to_generate=5,
        pilot_experiments=1,
        review_rounds=1,
        max_agent_iterations=20,
        search_depth="shallow",
        code_review=False,
        figure_quality="draft",
    ),
    "balanced": EffortConfig(
        papers_to_search=35,
        ideas_to_generate=10,
        pilot_experiments=2,
        review_rounds=2,
        max_agent_iterations=50,
        search_depth="moderate",
        code_review=True,
        figure_quality="publication",
    ),
    "max": EffortConfig(
        papers_to_search=50,
        ideas_to_generate=15,
        pilot_experiments=3,
        review_rounds=3,
        max_agent_iterations=80,
        search_depth="deep",
        code_review=True,
        figure_quality="publication",
    ),
    "beast": EffortConfig(
        papers_to_search=80,
        ideas_to_generate=25,
        pilot_experiments=5,
        review_rounds=4,
        max_agent_iterations=150,
        search_depth="exhaustive",
        code_review=True,
        figure_quality="publication",
    ),
}

ASSURANCE_CONFIGS = {
    "draft": AssuranceConfig(
        audit_mandatory=False,
        audit_blocking=False,
        citation_verify=False,
        proof_check=False,
        warn_blocking=False,
    ),
    "polished": AssuranceConfig(
        audit_mandatory=True,
        audit_blocking=True,
        citation_verify=False,
        proof_check=True,
        warn_blocking=False,
    ),
    "conference-ready": AssuranceConfig(
        audit_mandatory=True,
        audit_blocking=True,
        citation_verify=True,
        proof_check=True,
        warn_blocking=True,
    ),
    "submission": AssuranceConfig(
        audit_mandatory=True,
        audit_blocking=True,
        citation_verify=True,
        proof_check=True,
        warn_blocking=True,
    ),
}


def get_effort_config(effort: str) -> EffortConfig:
    return EFFORT_CONFIGS.get(effort, EFFORT_CONFIGS["balanced"])


def get_assurance_config(assurance: str) -> AssuranceConfig:
    return ASSURANCE_CONFIGS.get(assurance, ASSURANCE_CONFIGS["draft"])


def build_effort_prompt_section(effort: str, assurance: str) -> str:
    """生成注入到 Agent system prompt 的 effort/assurance 指令"""
    ec = get_effort_config(effort)
    ac = get_assurance_config(assurance)

    lines = [
        "## Effort & Assurance Configuration",
        "",
        f"- Effort level: **{effort}**",
        f"- Papers to search: {ec.papers_to_search}",
        f"- Ideas to generate: {ec.ideas_to_generate}",
        f"- Pilot experiments: {ec.pilot_experiments}",
        f"- Review rounds: {ec.review_rounds}",
        f"- Search depth: {ec.search_depth}",
        f"- Code review: {'yes' if ec.code_review else 'no'}",
        f"- Figure quality: {ec.figure_quality}",
        "",
        f"- Assurance level: **{assurance}**",
        f"- Audit mandatory: {'yes' if ac.audit_mandatory else 'no'}",
        f"- Audit blocking (FAIL stops submission): {'yes' if ac.audit_blocking else 'no'}",
        f"- Citation verification: {'yes' if ac.citation_verify else 'no'}",
        f"- Proof checking: {'yes' if ac.proof_check else 'no'}",
        f"- Warning blocks finalization: {'yes' if ac.warn_blocking else 'no'}",
    ]

    if assurance in {"conference-ready", "submission"}:
        lines.extend([
            "",
            "⚠️ SUBMISSION MODE: All audit layers MUST emit a verdict.",
            "If any layer returns FAIL or ERROR, the final report is BLOCKED.",
            "Use audit_verdict tool to record each layer's result.",
        ])

    return '\n'.join(lines)


