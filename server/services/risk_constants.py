"""Stable node dependency and textual risk contracts."""

import re

from ..contracts.workflow_nodes import WORKFLOW_NODES


def _protected_dependencies() -> dict[str, tuple[str, ...]]:
    closure: dict[str, tuple[str, ...]] = {}
    for node in WORKFLOW_NODES:
        upstream = []
        for parent in node["depends_on"]:
            upstream.extend((*closure[parent], parent))
        closure[node["id"]] = tuple(dict.fromkeys(upstream))
    return closure


PROTECTED_UPSTREAM = _protected_dependencies()

PENDING_RE = re.compile(
    r"(?:not\s+(?:yet\s+)?(?:run|executed|conducted|performed)|"
    r"no\s+(?:experiments?|training\s+runs?|evaluations?)\s+(?:have|has)\s+been\s+"
    r"(?:run|executed|conducted|performed)|"
    r"(?:experiments?|training\s+runs?)\s+(?:have|has)\s+not\s+been\s+"
    r"(?:run|executed|conducted|performed)|"
    r"(?:experiments?|runs?)\s+remain\s+to\s+be\s+(?:run|conducted|performed)|"
    r"yet\s+to\s+be\s+(?:run|executed|conducted|performed)|unexecuted|"
    r"pending|planned|no\s+(?:actual\s+)?(?:metric|result)|"
    r"no\s+provenance[- ]backed\s+measurements?|未运行|尚未(?:运行|执行|开展)|"
    r"还未(?:运行|执行|开展)|待运行|待执行|待验证|计划中)",
    re.IGNORECASE,
)

SUPPORTED_RE = re.compile(
    r"(?:outperform(?:s|ed)?|significant(?:ly)?\s+(?:better|improv)|"
    r"achiev(?:e|es|ed)\s+(?:state.of.the.art|superior)|"
    r"实验(?:证明|表明)|显著(?:优于|提升)|结果(?:证明|表明))",
    re.IGNORECASE,
)

CURRENT_METHOD_RE = re.compile(
    r"(?:we|our|proposed|this\s+(?:method|model|work)|本方法|本文|我们)",
    re.IGNORECASE,
)

NEGATED_SUPPORT_RE = re.compile(
    r"(?:cannot|does\s+not|has\s+not|have\s+not|had\s+not|"
    r"must\s+not|should\s+not|do\s+not|"
    r"not\s+(?:that|a\s+claim|evidence)|nor\s+that|no\s+evidence|"
    r"不能|无法|不得|不应|不支持|并非证据)",
    re.IGNORECASE,
)

PROSPECTIVE_RE = re.compile(
    r"(?:hypothes|expect|may|might|could|would|to\s+be\s+tested|假设|预期|可能|待验证)",
    re.IGNORECASE,
)

CONDITIONAL_SUPPORT_RE = re.compile(
    r"(?:\b(?:only\s+)?if\b|\bif\s+and\s+only\s+if\b|"
    r"\bprovided\s+that\b|\bcontingent\s+on\b|仅当|如果|若)",
    re.IGNORECASE,
)

PLACEHOLDER_RE = re.compile(
    r"(?:lorem\s+ipsum|your\s+(?:paper\s+)?title|your\s+abstract|"
    r"\b(?:todo|tbd)\b|"
    r"\bplaceholder\s+(?:text|content|title|abstract|figure|table|result|"
    r"value|citation|section)\b|\[\s*placeholder\s*\]|"
    r"insert\s+(?:text|figure|table|result)|"
    r"fill\s+(?:this|in)|\[\s*(?:what|why|how|title|method|dataset|metric)[^\]]*\]|"
    r"待补充|待填写|此处填写|占位符)",
    re.IGNORECASE,
)

LIMITATION_RE = re.compile(
    r"(?:limitation|caveat|constraint|boundary\s+condition|scope\s+restriction|"
    r"threat(?:s)?\s+to\s+validity|failure\s+(?:case|mode|analysis)|"
    r"negative\s+(?:case|result)|error\s+analysis|breakdown|edge\s+case|"
    r"局限|边界条件|适用范围|约束|有效性威胁|失败分析|失效模式|负结果|错误案例)",
    re.IGNORECASE,
)

UNCERTAINTY_RE = re.compile(
    r"(?:confidence\s+interval|credible\s+interval|interval\s+estimate|"
    r"\b(?:\d+(?:\.\d+)?\s*%\s*)?ci\b|\b(?:sd|se|iqr)\b|"
    r"standard\s+(?:deviation|error)|interquartile(?:\s+range)?|variance|"
    r"error\s+bars?|effect\s+size|bootstrap|permutation|wilcoxon|uncertainty|"
    r"置信区间|可信区间|标准差|标准误|四分位(?:距)?|方差|误差条|效应量|不确定性)",
    re.IGNORECASE,
)

SIMULATION_SCOPE_RE = re.compile(
    r"(?:benchmark|simulat(?:or|ion|ed)|controlled\s+(?:study|evaluation)|"
    r"defined\s+(?:evaluation\s+)?domain|registered\s+(?:scenario|condition)|"
    r"prespecified\s+(?:scenario|condition|setting)|evaluation\s+setting|"
    r"testbed|仿真|模拟|受控研究|受控评估|定义域|预设场景|注册条件|评估范围)",
    re.IGNORECASE,
)

SEARCH_PROTOCOL_RE = re.compile(
    r"(?:search\s+protocol|search\s+strategy|inclusion\s+criteria|exclusion\s+criteria|"
    r"database|query|检索协议|检索策略|纳入标准|排除标准|数据库|检索式)",
    re.IGNORECASE,
)

NODE_RISK_CHECKLIST: dict[str, tuple[str, ...]] = {
    "lit": (
        "canonical survey and BibTeX integrity",
        "search-window, coverage, and source traceability",
        "citation closure, critical synthesis, and evidence gaps",
    ),
    "idea": (
        "candidate boundaries and stable IDs",
        "hypothesis, mechanism, nearest work, falsification, and feasibility",
        "citation closure and unresolved template content",
    ),
    "novelty": (
        "selected-idea schema and traceability",
        "claim-level nearest-work comparison and uncertainty boundary",
        "optional patent-screen provenance and limitations",
    ),
    "exp-design": (
        "frozen mechanism and claim implementation mapping",
        "runnable command, configuration, source syntax, and seeds",
        "split leakage, controls, ablations, statistics, and failure criteria",
    ),
    "exp-run": (
        "explicit no-run state or immutable successful-run provenance",
        "attempt status, config/result hashes, logs, and anomaly quarantine",
        "stale or unowned metric isolation",
    ),
    "results": (
        "executed-versus-planned evidence boundary",
        "claim decisions, uncertainty, independent unit, and failure analysis",
        "analysis freshness relative to owned metric artifacts",
    ),
    "figure": (
        "scientific question and frozen-claim binding",
        "editable source, preview, hash, and manifest consistency",
        "semantic duplication, meaningful naming, and quantitative provenance",
    ),
    "narrative": (
        "frozen idea, claim, mechanism, and falsification continuity",
        "evidence maturity, negative evidence, and limitations",
        "source-bundle and output hash freshness",
    ),
    "paper": (
        "claim and citation closure",
        "required scientific argument sections and unresolved placeholders",
        "figure references, evidence maturity, and upstream freshness",
    ),
    "review": (
        "structured independent review rounds",
        "critical finding resolution and bounded outcome",
        "review-to-paper provenance and reviewer identity",
    ),
    "audit": (
        "exact five-layer coverage and inspected evidence",
        "ERROR/FAIL preservation and responsible-stage routing",
        "audit freshness against the inspected research record",
    ),
    "compile": (
        "real PDF signature and current TeX source bundle",
        "hash-bound build record and unresolved reference diagnostics",
        "soft page target and non-fatal layout warnings",
    ),
    "ppt": (
        "complete Beamer source and valid current PDF",
        "paper-level claim maturity, citations, and selected figures",
        "hash-bound slide build and presentation legibility",
    ),
}
