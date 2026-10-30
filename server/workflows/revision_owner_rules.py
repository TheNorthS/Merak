"""Ordered ownership markers; structured owners take precedence over heuristics."""

DETERMINISTIC_COMPILE_MARKERS = (
    "compile-hash-",
    "compile-stale-",
    "compile-build-",
    "compile-pdf-",
    "paper_build.json",
    "source hash does not match",
    "source_bundle_sha256",
    "pdf hash does not match",
    "compiled pdf is older",
    "stale build",
    "build record",
)

STALE_CONSUMER_MARKERS = {
    "paper": (
        "scientific inputs changed after paper freeze",
        "staged paper state is stale relative to scientific inputs",
        "authoritative paper-input hashes changed after the manuscript scientific freeze",
    ),
    "review": (
        "review_state source bundle is stale",
        "structured review is not hash-bound",
        "visual review is stale",
        "reviewed snapshot is stale",
        "final snapshot is stale",
    ),
    "audit": (
        "audit results predate",
        "audit source bundle hash does not match",
        "audit runtime component hashes are missing or stale",
    ),
    "ppt": (
        "slide source has no paper/research source-bundle record",
        "slide plan source bundle is stale",
        "slide pdf is older than",
    ),
}

PATH_OWNER_RULES = (
    ("novelty", ("ideas/selected_idea.json", "ideas/novelty_report.md")),
    ("idea", ("ideas/ideas.md",)),
    ("results", ("experiments/results/analysis.md", "results/analysis.md")),
    (
        "exp-run",
        (
            "experiments/logs/",
            "experiments/checkpoints/",
            "experiments/execution",
            "experiments/run_status",
            ".merak/experiments/",
            "experiments/results/",
            "metrics.json",
            "predictions",
        ),
    ),
    (
        "exp-design",
        (
            "experiments/src/",
            "experiments/configs/",
            "experiments/method_contract",
            "experiments/run_spec",
            "experiments/experiment_plan",
        ),
    ),
    ("figure", ("figures/", "paper/figures/", "slides/figures/")),
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
    ("ppt", ("slides/",)),
    ("paper", ("paper/",)),
)

SEMANTIC_OWNER_RULES = (
    (
        "exp-run",
        (
            "experiment was not run",
            "experiments were not run",
            "training failed",
            "run failed",
            "job failed",
            "missing run log",
            "missing checkpoint",
            "runtime crash",
            "未运行实验",
            "实验未运行",
            "训练失败",
            "运行失败",
            "缺少运行日志",
            "缺少检查点",
        ),
    ),
    (
        "results",
        (
            "statistical test",
            "confidence interval",
            "uncertainty",
            "per-seed",
            "per seed",
            "provenance",
            "prediction file",
            "effect size",
            "significance",
            "统计检验",
            "置信区间",
            "不确定性",
            "随机种子",
            "结果溯源",
            "效应量",
            "显著性",
        ),
    ),
    (
        "exp-design",
        (
            "missing baseline",
            "missing ablation",
            "unfair baseline",
            "data leakage",
            "split protocol",
            "implementation mismatch",
            "configuration mismatch",
            "method contract",
            "control group",
            "缺少基线",
            "缺少消融",
            "数据泄漏",
            "划分协议",
            "实现不一致",
            "配置不一致",
            "方法契约",
            "对照组",
        ),
    ),
    ("figure", ("figure is missing", "invalid figure", "图缺失", "图表错误")),
    (
        "lit",
        (
            "missing citation",
            "prior art",
            "prior-art",
            "literature coverage",
            "缺少引用",
            "现有工作",
            "文献覆盖",
        ),
    ),
)

PLATFORM_MARKERS = (
    "latexmk not found",
    "compilation timed out",
    "cleanup timed out",
    "cleanup failed",
)

BIBLIOGRAPHY_MARKERS = (
    ".bbl",
    ".blg",
    "references.bib",
    "bibtex error",
    "bibtex failed",
)

SOURCE_MARKERS = (
    "undefined control sequence",
    "emergency stop",
    "runaway argument",
    "missing \\begin",
    "missing }",
    "missing $ inserted",
    "extra }",
    "misplaced",
    "unicode character",
)

PROOF_CONTENT_MARKERS = (
    "counterexample",
    "invalid proof",
    "incorrect proof",
    "proof gap",
    "logical gap",
    "unproven theorem",
    "missing proof",
    "theorem is false",
    "lemma is false",
    "claim does not follow",
    "反例",
    "证明错误",
    "证明缺口",
    "逻辑错误",
    "定理不成立",
    "缺少证明",
)
