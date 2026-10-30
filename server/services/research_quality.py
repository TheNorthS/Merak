"""Deterministic research-depth checks for workflow artifacts."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


@dataclass(frozen=True)
class QualityDimension:
    name: str
    patterns: tuple[str, ...]
    description: str


PHASE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "lit": ("literature/survey.md", "literature/references.bib"),
    "idea": ("ideas/ideas.md",),
    "novelty": ("ideas/novelty_report.md",),
    "exp-design": ("experiments/EXPERIMENT_PLAN.md",),
    "results": ("experiments/results/analysis.md",),
    "narrative": ("NARRATIVE_REPORT.md",),
}


PHASE_DIMENSIONS: dict[str, tuple[QualityDimension, ...]] = {
    "lit": (
        QualityDimension("search_protocol", (r"search protocol", r"检索(策略|协议|范围|方法)"), "explicit databases, queries, and time window"),
        QualityDimension("taxonomy", (r"taxonomy", r"主题分类", r"研究脉络", r"类别"), "structured literature taxonomy rather than a paper list"),
        QualityDimension("comparison", (r"\|[^\n]+\|[^\n]+\|", r"compare", r"对比"), "cross-paper comparison by assumptions, data, and evidence"),
        QualityDimension("critical_synthesis", (r"limitation", r"局限", r"争议", r"inconsisten", r"conflict"), "critical synthesis of limitations or conflicting findings"),
        QualityDimension("evidence_gap", (r"evidence gap", r"证据缺口", r"open problem", r"未解决"), "explicit evidence gaps tied to the research question"),
        QualityDimension("future_test", (r"falsif", r"可证伪", r"next experiment", r"验证实验", r"下一步"), "testable next-step implications"),
    ),
    "idea": (
        QualityDimension("problem_anchor", (r"problem", r"研究问题", r"痛点", r"problem anchor"), "a concrete scientific problem and scope"),
        QualityDimension("falsifiable_hypothesis", (r"hypothesis", r"核心假设", r"可证伪"), "a falsifiable hypothesis, not a feature wishlist"),
        QualityDimension("mechanism", (r"mechanism", r"机制", r"why it should", r"作用路径"), "a plausible mechanism connecting method to expected effect"),
        QualityDimension("novelty_delta", (r"novelty delta", r"创新增量", r"差异", r"nearest work", r"最近邻"), "delta against the nearest prior method"),
        QualityDimension("anti_claim", (r"anti-claim", r"反声明", r"rule out", r"排除"), "alternative explanations that experiments must rule out"),
        QualityDimension("falsification", (r"falsif", r"失败条件", r"negative result", r"证伪"), "failure and pivot criteria"),
        QualityDimension("feasibility", (r"feasibility", r"可行性", r"resource", r"算力", r"data requirement", r"数据要求"), "data, compute, and implementation feasibility"),
    ),
    "novelty": (
        QualityDimension("nearest_neighbors", (r"nearest", r"最近邻", r"most related", r"最相关"), "named nearest-neighbor papers or systems"),
        QualityDimension("search_evidence", (r"arxiv", r"doi", r"semantic scholar", r"citation", r"引用"), "retrieval evidence rather than memory-only judgment"),
        QualityDimension("claim_delta", (r"delta", r"差异", r"overlap", r"重叠"), "claim-level overlap and delta analysis"),
        QualityDimension("novelty_risk", (r"risk", r"风险", r"duplicate", r"重复"), "duplication and incremental-contribution risk"),
        QualityDimension("verdict", (r"high|medium|low|duplicate", r"高|中|低|重复"), "explicit novelty verdict"),
        QualityDimension("decision", (r"recommend", r"推荐", r"reject", r"淘汰"), "evidence-backed selection decision"),
    ),
    "exp-design": (
        QualityDimension("claim_evidence", (r"claim.?[- ]?to.?[- ]?evidence", r"claim.?evidence", r"声明.?证据", r"核心 claim"), "claim-to-evidence matrix"),
        QualityDimension("data_split", (r"dataset", r"数据集", r"population", r"sample", r"corpus", r"instance", r"scenario", r"analysis unit", r"研究对象", r"样本", r"分析单位", r"manifest", r"split", r"划分"), "study material, independent analysis units, sampling, partitions, or scenarios"),
        QualityDimension("leakage_control", (r"leak", r"泄漏", r"independen", r"group.?split", r"confound", r"bias", r"contamin", r"blinding", r"triangulat", r"混杂", r"偏倚", r"污染", r"盲法", r"三角互证"), "independence, leakage, confounding, contamination, or interpretive-bias controls"),
        QualityDimension("baselines", (r"baseline", r"基线", r"comparator", r"control (?:group|condition)", r"reference (?:method|condition|standard)", r"alternative explanation", r"对照", r"参照", r"公平对比"), "strong comparators, reference conditions, or alternative explanations under a fair design"),
        QualityDimension("ablations", (r"ablation", r"消融", r"component", r"sensitivity", r"necessity", r"assumption", r"negative case", r"robustness", r"敏感性", r"必要性", r"假设", r"负例", r"稳健性"), "mechanism-necessity, assumption, negative-case, or design-sensitivity tests"),
        QualityDimension("statistics", (r"confidence interval", r"credible interval", r"置信区间", r"可信区间", r"effect size", r"效应量", r"bootstrap", r"statistical", r"estimand", r"uncertainty", r"saturation", r"显著性", r"估计目标", r"不确定性", r"饱和"), "design-appropriate uncertainty, estimand, effect-size, saturation, or verification plan"),
        QualityDimension(
            "reproducibility",
            (
                r"seed", r"随机种子", r"version", r"版本", r"config",
                r"protocol", r"registry", r"preregister", r"预注册",
                r"codebook", r"coding manual", r"adjudicat", r"saturation memo",
                r"assumption registry", r"checker build", r"certificate",
                r"cohort snapshot", r"corpus snapshot", r"batch id",
                r"decision ledger", r"provenance", r"hash",
            ),
            "replicate/configuration, protocol/registry, corpus/codebook, proof/checker, or study-ledger provenance",
        ),
        QualityDimension("falsification", (r"anti-claim", r"falsif", r"失败条件", r"证伪", r"rule out"), "tests that can refute the proposed explanation"),
        QualityDimension("resource_budget", (r"compute", r"算力", r"gpu", r"runtime", r"运行时间", r"budget", r"sample size", r"recruit", r"laboratory", r"fieldwork", r"proof complexity", r"feasibility", r"样本量", r"招募", r"实验室", r"田野", r"证明复杂度", r"可行性"), "compute, sampling, laboratory, fieldwork, verification, and run-order feasibility"),
    ),
    "results": (
        QualityDimension(
            "provenance",
            (
                r"provenance", r"来源", r"artifact", r"run_id", r"证据",
                r"study[_ -]?id", r"cohort[_ -]?id", r"protocol[_ -]?id",
                r"registry[_ -]?id", r"corpus[_ -]?(?:id|version|snapshot)",
                r"checker[_ -]?build", r"proof[_ -]?(?:id|hash|certificate)",
                r"coding[_ -]?(?:ledger|version)", r"adjudication[_ -]?ledger",
                r"assay[_ -]?batch", r"sample[_ -]?batch",
            ),
            "structured scientific-source identity plus corroborating artifact/configuration provenance",
        ),
        QualityDimension("uncertainty", (r"confidence interval", r"credible interval", r"interval estimate", r"\b(?:ci|sd|se|iqr)\b", r"standard (?:deviation|error)", r"interquartile", r"variance", r"error bar", r"置信区间", r"可信区间", r"标准差", r"标准误", r"四分位", r"方差", r"uncertainty", r"pending", r"未运行"), "uncertainty or an explicit not-run state"),
        QualityDimension("claim_mapping", (r"claim", r"声明", r"support", r"支持", r"unsupported", r"不支持"), "which claims are supported, contradicted, or pending"),
        QualityDimension(
            "failure_analysis",
            (
                r"failure", r"failure mode", r"breakdown", r"edge case",
                r"negative case", r"error analysis", r"residual analysis",
                r"misclassif", r"where .* fails?", r"caveat", r"shortcoming",
                r"limitation", r"失败", r"失效", r"误差分析", r"残差分析",
                r"错误案例", r"边界案例", r"局限",
            ),
            "failure cases and limitations",
        ),
    ),
    "narrative": (
        QualityDimension("motivation", (r"motivation", r"rationale", r"problem context", r"significance", r"research need", r"evidence gap", r"why (?:this|the)", r"动机", r"背景", r"意义", r"问题缘由", r"研究需求"), "problem motivation"),
        QualityDimension("method", (r"method", r"approach", r"framework", r"architecture", r"procedure", r"mechanism", r"proposed (?:model|system)", r"方法", r"方案", r"框架", r"架构", r"流程", r"机制"), "method mechanism"),
        QualityDimension("evidence", (r"evidence", r"experiment", r"evaluation", r"finding", r"result", r"observation", r"measurement", r"validation", r"empirical analysis", r"证据", r"实验", r"评估", r"发现", r"结果", r"观测", r"测量", r"验证"), "artifact-backed evidence state"),
        QualityDimension("claims", (r"claim", r"hypothesis", r"conclusion", r"inference", r"interpretation", r"supported", r"confirmed", r"refuted", r"contradicted", r"inconclusive", r"pending", r"声明", r"假设", r"结论", r"推断", r"解释", r"支持", r"证实", r"反驳", r"不确定", r"待验证"), "claim status boundaries"),
        QualityDimension("limitations", (r"limitation", r"threat", r"boundary condition", r"scope", r"caveat", r"constraint", r"failure mode", r"bias", r"validity", r"risk", r"局限", r"威胁", r"边界条件", r"适用范围", r"约束", r"偏差", r"有效性", r"风险"), "limitations and threats to validity"),
    ),
}


CRITICAL_DIMENSIONS: dict[str, frozenset[str]] = {
    "lit": frozenset({"comparison", "evidence_gap"}),
    "idea": frozenset({"falsifiable_hypothesis", "mechanism"}),
    "novelty": frozenset({"search_evidence", "decision"}),
    "exp-design": frozenset({"claim_evidence", "data_split", "falsification"}),
    "results": frozenset({"provenance", "claim_mapping"}),
    "narrative": frozenset({"evidence", "claims"}),
}


def _planned_provenance_markers(text: str) -> list[str]:
    planned = re.search(
        r"planned result analysis\s*\(not evidence\)", text, re.IGNORECASE
    )
    no_measurement = re.search(
        r"contains no measured performance|no scientific experiment execution|"
        r"evidence status\s*:\s*planned\s*/\s*pending",
        text,
        re.IGNORECASE,
    )
    pending = re.search(r"\bpending\b|待验证|未运行", text, re.IGNORECASE)
    if planned and no_measurement and pending:
        return ["structured:planned_no_run", "structured:no_measurement_claimed"]
    return []


def _provenance_field_patterns() -> dict[str, str]:
    return {
        "source_run_id": r"source[_ -]?run[_ -]?id|来源运行(?:标识|id)",
        "run_id": r"run[_ -]?id|运行(?:标识|id)",
        "simulation_id": r"simulation[_ -]?id|仿真(?:标识|id)",
        "study_id": r"study[_ -]?id|研究(?:标识|编号|id)",
        "cohort_id": r"cohort[_ -]?id|队列(?:标识|编号|id)",
        "protocol_id": (
            r"protocol[_ -]?(?:id|version)|registry[_ -]?id|"
            r"registered[_ -]?protocol|协议(?:标识|编号|版本)|注册(?:标识|编号)"
        ),
        "corpus_id": r"corpus[_ -]?(?:id|version|snapshot)|语料(?:标识|编号|版本|快照)",
        "checker_build_id": (
            r"checker[_ -]?(?:build[_ -]?id|build|version)|"
            r"proof[_ -]?(?:id|certificate[_ -]?id)|检查器(?:构建标识|版本)|"
            r"证明(?:标识|证书标识)"
        ),
        "coding_ledger_id": (
            r"coding[_ -]?(?:ledger[_ -]?id|version)|"
            r"adjudication[_ -]?(?:ledger[_ -]?id|version)|"
            r"编码(?:台账标识|版本)|裁决(?:台账标识|版本)"
        ),
        "batch_id": r"(?:assay|sample|site)[_ -]?batch[_ -]?id|(?:测定|样本|站点)批次(?:标识|编号|id)",
        "manifest": r"(?:simulation[_ -]?|evidence[_ -]?|result[_ -]?)?manifest(?:[_ -]?path)?|(?:仿真|证据|结果)?清单(?:路径)?",
        "artifact": r"(?:metric[_ -]?|result[_ -]?)?artifact(?:[_ -]?path)?|(?:指标|结果)?产物(?:路径)?",
        "digest": (
            r"(?:manifest|artifact|result|source|corpus|protocol|proof|certificate|"
            r"codebook|cohort|batch)[_ -]?(?:sha256|digest|hash)|"
            r"(?:清单|产物|结果|来源|语料|协议|证明|证书|编码本|队列|批次)(?:摘要|哈希)"
        ),
        "seed": r"(?:simulation[_ -]?)?seed|(?:仿真)?随机种子",
        "config": r"(?:resolved[_ -]?)?(?:config|configuration)[_ -]?(?:id|version|hash)|(?:解析后)?配置(?:标识|版本|哈希)",
    }


class ResearchQualityService:
    MODE_FACTORS = {"off": 0.0, "standard": 0.48, "rigorous": 0.58}
    ASSURANCE_BONUS = {
        "draft": 0.0,
        "polished": 0.08,
        "conference-ready": 0.16,
        "submission": 0.20,
    }

    @staticmethod
    def _read(root: Path, relative_paths: tuple[str, ...]) -> tuple[str, list[str], list[str]]:
        chunks: list[str] = []
        found: list[str] = []
        missing: list[str] = []
        for relative in relative_paths:
            path = root / relative
            if not path.is_file() or path.stat().st_size == 0:
                missing.append(relative)
                continue
            found.append(relative)
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n\n".join(chunks), found, missing

    @staticmethod
    def _reference_count(text: str) -> int:
        return len(re.findall(r"(?m)^\s*@[A-Za-z]+\s*\{", text))

    @staticmethod
    def _structured_field_values(
        text: str,
        field_pattern: str,
    ) -> list[str]:
        """Return non-placeholder values from explicit provenance fields."""
        assignment = re.compile(
            rf"(?im)(?<![\w-])(?:{field_pattern})(?![\w-])\s*[:=]\s*"
            rf"(?:[`\"'])?([^\s,;|}}\]\n`\"']+)",
        )
        table = re.compile(
            rf"(?im)^\s*\|\s*(?:`)?(?:{field_pattern})(?:`)?\s*\|\s*"
            rf"(?:`)?([^|\n`]+?)(?:`)?\s*\|",
        )
        invalid_values = {
            "-", "--", "n/a", "na", "none", "null", "unknown", "pending",
            "tbd", "todo", "not-run", "not_run", "未运行", "待补充", "未知",
        }
        values: list[str] = []
        for match in (*assignment.finditer(text), *table.finditer(text)):
            value = match.group(1).strip().strip("`\"'.,;:[]{}()")
            folded = value.casefold()
            if (
                not value
                or folded in invalid_values
                or folded.startswith(
                    ("replace_", "replace-with", "placeholder")
                )
                or (value.startswith("<") and value.endswith(">"))
            ):
                continue
            values.append(value)
        return values

    @classmethod
    def _results_provenance_matches(cls, text: str) -> list[str]:
        """Require a structured run identity plus corroborating provenance."""
        # A design-only workflow has deliberately produced no measurement, so
        # there cannot be a run identity to cite.  Treat the deterministic
        # planned-result contract as a valid provenance state only when it is
        # explicit about both absence of evidence and pending claims.  This
        # avoids the historical 0.75/0.78 loop while keeping empirical prose
        # subject to the strict identity contract below.
        planned_markers = _planned_provenance_markers(text)
        if planned_markers:
            return planned_markers
        fields = _provenance_field_patterns()
        evidence = {
            name: cls._structured_field_values(text, pattern)
            for name, pattern in fields.items()
        }
        identity_names = [
            name
            for name in (
                "source_run_id", "run_id", "simulation_id", "study_id",
                "cohort_id", "protocol_id", "corpus_id", "checker_build_id",
                "coding_ledger_id", "batch_id",
            )
            if evidence[name]
        ]
        corroborating_names = [
            name
            for name in ("manifest", "artifact", "digest", "seed", "config")
            if evidence[name]
        ]
        if not identity_names or not corroborating_names:
            return []
        return [
            f"structured:{name}"
            for name in (*identity_names, *corroborating_names)
        ]

    @classmethod
    def _dimension_matches(
        cls,
        node_id: str,
        dimension: QualityDimension,
        text: str,
    ) -> list[str]:
        if node_id == "results" and dimension.name == "provenance":
            return cls._results_provenance_matches(text)
        return [
            pattern
            for pattern in dimension.patterns
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        ]

    def evaluate(
        self,
        project_path: str,
        node_id: str,
        assurance: str = "draft",
        mode: str = "rigorous",
    ) -> dict[str, Any]:
        dimensions = PHASE_DIMENSIONS.get(node_id)
        artifacts = PHASE_ARTIFACTS.get(node_id)
        if not dimensions or not artifacts or mode == "off":
            return {"applicable": False, "passed": True, "score": 1.0, "issues": []}

        root = Path(project_path).expanduser().resolve()
        text, found, missing = self._read(root, artifacts)
        dimension_results: list[dict[str, Any]] = []
        for dimension in dimensions:
            matched = self._dimension_matches(node_id, dimension, text)
            dimension_results.append({
                "name": dimension.name,
                "passed": bool(matched),
                "description": dimension.description,
                "matched_patterns": matched[:3],
            })

        score = sum(1 for item in dimension_results if item["passed"]) / len(dimension_results)
        issues = [
            f"missing quality dimension {item['name']}: {item['description']}"
            for item in dimension_results
            if not item["passed"]
        ]
        issues.extend(f"missing artifact: {item}" for item in missing)

        if node_id == "lit":
            references = self._reference_count(text)
            if references < 8:
                issues.append(f"literature coverage too small: {references} BibTeX entries; need at least 8")
                score = max(0.0, score - 0.12)
        else:
            references = None

        threshold = min(
            0.85,
            self.MODE_FACTORS.get(mode, self.MODE_FACTORS["rigorous"])
            + self.ASSURANCE_BONUS.get(assurance, 0.0),
        )
        score = round(score, 4)
        critical_names = CRITICAL_DIMENSIONS.get(node_id, frozenset())
        critical_missing = [
            item["name"]
            for item in dimension_results
            if item["name"] in critical_names and not item["passed"]
        ]
        all_critical_missing = bool(critical_names) and len(critical_missing) == len(critical_names)
        hard_failure = bool(missing) or score < 0.34 or all_critical_missing
        report = {
            "schema": 1,
            "node_id": node_id,
            "mode": mode,
            "assurance": assurance,
            "applicable": True,
            "passed": not missing and score >= threshold,
            "score": score,
            "threshold": threshold,
            "hard_failure": hard_failure,
            "critical_dimensions": sorted(critical_names),
            "critical_missing": critical_missing,
            "artifacts": found,
            "missing_artifacts": missing,
            "reference_count": references,
            "dimensions": dimension_results,
            "issues": issues,
            "evaluated_at": time.time(),
        }
        output = root / ".merak" / "quality" / f"{node_id}.json"
        atomic_write_json(output, report)
        report["report_path"] = str(output)
        return report

    def apply_gate(
        self,
        gate: dict[str, Any],
        project_path: str,
        node_id: str,
        assurance: str,
        mode: str,
    ) -> dict[str, Any]:
        report = self.evaluate(project_path, node_id, assurance, mode)
        if not report.get("applicable"):
            return gate
        details = gate.setdefault("details", {})
        if not isinstance(details, dict):
            details = {}
            gate["details"] = details
        if not report.get("passed"):
            threshold_blocking = assurance in {
                "polished",
                "conference-ready",
                "submission",
            }
            should_block = bool(report.get("hard_failure")) or threshold_blocking
            report["blocking"] = should_block
            details["research_quality"] = report
            if not gate.get("accepted"):
                return gate
            if should_block:
                return {
                    "accepted": False,
                    "reason": "research depth contract failed",
                    "summary": f"quality score {report['score']:.2f} < {report['threshold']:.2f}; " + "; ".join(report["issues"][:5]),
                    "details": {"research_quality": report},
                }
            gate.setdefault("warnings", []).append({
                "kind": "research_quality",
                "score": report["score"],
                "threshold": report["threshold"],
                "issues": report["issues"][:8],
                "report_path": report.get("report_path", ""),
            })
            gate["summary"] = (
                f"{gate.get('summary', '')} Research quality advisory "
                f"{report['score']:.2f}/{report['threshold']:.2f}; downstream refinement required."
            ).strip()
            return gate
        report["blocking"] = False
        details["research_quality"] = report
        if not gate.get("accepted"):
            return gate
        gate["summary"] = f"{gate.get('summary', '')} Research quality {report['score']:.2f}/{report['threshold']:.2f}.".strip()
        return gate


research_quality_service = ResearchQualityService()
