"""Route audit counterevidence by producer ownership before layer fallback."""

from __future__ import annotations

from typing import Any, Iterable


AUDIT_PATH_OWNER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("results", ("experiments/results/analysis.md", "results/analysis.md")),
    (
        "exp-run",
        (
            ".merak/experiments/",
            "experiments/logs/",
            "experiments/checkpoints/",
            "experiments/results/",
            "metrics.json",
            "predictions",
        ),
    ),
    (
        "exp-design",
        (
            "experiments/experiment_plan",
            "experiments/method_contract",
            "experiments/run_spec",
            "experiments/configs/",
            "experiments/src/",
        ),
    ),
    ("figure", ("figures/", "paper/figures/")),
    ("narrative", ("narrative_report.md", "paper/paper_plan.md")),
    ("lit", ("literature/", "references.bib")),
    ("review", ("review-stage/",)),
    (
        "audit",
        (
            "audit-results/",
            "paper/proof_audit.json",
            ".merak/proof-audit/",
            ".merak/proof_checker/",
        ),
    ),
    ("paper", ("paper/",)),
)


AUDIT_SEMANTIC_OWNER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "exp-run",
        (
            "runtime",
            "execution",
            "run log",
            "checkpoint",
            "training failed",
            "job failed",
            "运行日志",
            "执行失败",
            "训练失败",
        ),
    ),
    (
        "results",
        (
            "statistical",
            "uncertainty",
            "effect size",
            "result analysis",
            "claim-to-result",
            "统计",
            "不确定性",
            "效应量",
            "结果分析",
        ),
    ),
    (
        "exp-design",
        (
            "experimental design",
            "baseline",
            "ablation",
            "data leakage",
            "split protocol",
            "method contract",
            "实验设计",
            "基线",
            "消融",
            "数据泄漏",
            "划分协议",
        ),
    ),
    ("figure", ("figure", "plot", "visualization", "图表", "科研绘图")),
    ("lit", ("citation source", "prior art", "literature", "文献", "引用来源")),
    ("review", ("review integrity", "review trace", "审稿", "评审")),
    (
        "paper",
        (
            "manuscript",
            "paper claim",
            "overclaim",
            "unsupported claim",
            "proof",
            "theorem",
            "论文",
            "过度声明",
            "证明",
            "定理",
        ),
    ),
)


def audit_failure_owner(
    item: dict[str, Any], layer: int, evidence: Iterable[str]
) -> str:
    """Route counterevidence to the artifact producer, not a fixed audit layer."""
    paths = [
        str(value).replace("\\", "/").casefold()
        for value in evidence
        if str(value).strip()
    ]
    semantic_text = " ".join(
        (
            str(item.get(key) or "")
            for key in ("category", "summary", "details", "layer_name")
        )
    ).casefold()
    proof_counterevidence = any(
        (
            marker in semantic_text
            for marker in (
                "invalid proof",
                "proof gap",
                "counterexample",
                "theorem is false",
                "unsupported claim",
                "证明错误",
                "证明缺口",
                "反例",
                "定理不成立",
            )
        )
    )
    if proof_counterevidence:
        return "paper"
    for owner, markers in AUDIT_PATH_OWNER_RULES:
        if any((marker in path for path in paths for marker in markers)):
            return owner
    for owner, markers in AUDIT_SEMANTIC_OWNER_RULES:
        if any((marker in semantic_text for marker in markers)):
            return owner
    return {1: "exp-design", 2: "results", 3: "paper", 4: "paper", 5: "paper"}.get(
        layer, "audit"
    )
