"""Plan scientific figures and tables from contracts and executed evidence.

The asset plan is deliberately domain-neutral.  It binds every paper asset to a
research question, claim, source artifact, and evidence status. Numeric records
are accepted only when their file hash is owned by a successful runtime event or
by a cited public-data manifest with a matching SHA256. Planning templates and
preview values are never promoted to evidence.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from ..utils.atomic_write import atomic_write_bytes
from .scientific_record_models import (
    QualitativeEvidenceRecord as QualitativeEvidenceRecord,
    ResultRecord as ResultRecord,
)
from .scientific_evidence_sources import ScientificEvidenceSourcesMixin
from .scientific_numeric_parsing import ScientificNumericParsingMixin

try:
    import yaml
except ImportError:  # pragma: no cover - server dependencies include PyYAML.
    yaml = None


_METRIC = re.compile(
    r"(?:accuracy|acc|f1|auroc|auc|precision|recall|specificity|sensitivity|"
    r"loss|nll|ece|brier|rmse|mae|mse|r2|score|bleu|rouge|perplexity|ppl|"
    r"hazard[_ ]?ratio|odds[_ ]?ratio|risk[_ ]?ratio|relative[_ ]?risk|"
    r"effect[_ ]?size|mean[_ ]?difference|coefficient|estimate|beta|"
    r"log2?[_ ]?fold[_ ]?change|fold[_ ]?change|concentration|response|yield|"
    r"survival|event[_ ]?rate|mortality|c[_ -]?index|concordance|"
    r"net[_ ]?benefit|calibration[_ ]?(?:slope|intercept)|"
    r"throughput|latency|p50|p90|p95|p99|qps|bandwidth|runtime|speedup|"
    r"memory|energy|power|cost|efficiency|fdr|q[_ ]?value|adjusted[_ ]?p|"
    r"upper[_ ]?bound|lower[_ ]?bound|error[_ ]?bound|regret|complexity|"
    r"convergence[_ ]?rate|approximation[_ ]?ratio)",
    re.IGNORECASE,
)
_NON_SCIENTIFIC_PATH = re.compile(
    r"(?:^|/)(?:templates?|placeholders?|demo|simulated|simulation)(?:/|$)"
    r"|(?:planned|template|demo|synthetic[_ -]?preview)"
    r"|(?:^|/)(?:history|training_history|learning_curve)\.(?:csv|json)$",
    re.IGNORECASE,
)
_ABLATION = re.compile(
    r"(?:ablation|component|w/o|without|remove[ d]?|no[_ -]|disable[ d]?|ablated)",
    re.IGNORECASE,
)
_ROBUSTNESS = re.compile(
    r"(?:robust|stress|corrupt|noise|severity|missing|drop(?:out)?|shift|perturb|"
    r"subgroup|external|sensitivity|dose|concentration|time[_ -]?point|"
    r"workload|scale|cohort|condition)",
    re.IGNORECASE,
)

ARCHETYPE_PLOT_ROLES: dict[str, dict[str, str]] = {
    "algorithm_benchmark": {
        "result": "interval_comparison",
        "ablation": "matched_control_comparison",
        "robustness": "stress_curve",
        "calibration": "risk_coverage",
    },
    "systems_testbed": {
        "result": "tradeoff_frontier",
        "ablation": "matched_control_comparison",
        "robustness": "scaling_curve",
        "calibration": "tail_latency",
    },
    "observational_cohort": {
        "result": "forest_effect",
        "ablation": "coefficient_plot",
        "robustness": "subgroup_forest",
        "calibration": "sensitivity",
    },
    "diagnostic_prognostic": {
        "result": "forest_effect",
        "ablation": "coefficient_plot",
        "robustness": "subgroup_forest",
        "calibration": "calibration",
    },
    "intervention_trial": {
        "result": "forest_effect",
        "ablation": "subgroup_forest",
        "robustness": "time_to_event",
        "calibration": "decision_curve",
    },
    "omics_discovery": {
        "result": "volcano_effect",
        "ablation": "cohort_sensitivity",
        "robustness": "cohort_sensitivity",
        "calibration": "pathway_enrichment",
    },
    "controlled_experiment": {
        "result": "replicate_distribution",
        "ablation": "dot_interval",
        "robustness": "dose_response",
        "calibration": "time_course",
    },
    "simulation_modeling": {
        "result": "convergence",
        "ablation": "sensitivity",
        "robustness": "sensitivity",
        "calibration": "phase_diagram",
    },
    "formal_theory": {
        "result": "bound_comparison",
        "ablation": "counterexample",
        "robustness": "counterexample",
        "calibration": "phase_diagram",
    },
    "qualitative_mixed": {
        "result": "evidence_matrix",
        "ablation": "case_comparison",
        "robustness": "case_comparison",
        "calibration": "theme_map",
    },
    "generic_empirical": {
        "result": "interval_comparison",
        "ablation": "matched_control_comparison",
        "robustness": "sensitivity",
        "calibration": "calibration",
    },
}

def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _contract_json(path: Path) -> dict[str, Any]:
    """Read a canonical scientific contract without hiding corruption."""
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Scientific contract is missing or empty: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Scientific contract is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Scientific contract root must be an object: {path}")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_name(value: Any, fallback: str = "", limit: int = 100) -> str:
    clean = " ".join(str(value or "").replace("_", " ").split()).strip(
        " \t\r\n\"'*_"
    )
    return clean[: max(20, int(limit))] or fallback


def _first(mapping: dict[str, Any], names: Iterable[str]) -> Any:
    lowered = {str(key).casefold(): value for key, value in mapping.items()}
    for name in names:
        if name.casefold() in lowered and str(lowered[name.casefold()]).strip():
            return lowered[name.casefold()]
    return ""


class ScientificAssetService(
    ScientificEvidenceSourcesMixin,
    ScientificNumericParsingMixin,
):
    """Build a persistent claim-to-asset plan and derived plotting tables."""

    plan_relative_path = Path("figures/SCIENTIFIC_ASSET_PLAN.json")
    aggregate_relative_dir = Path("experiments/results/aggregates")

    @staticmethod
    def _implementation_architecture_blueprint(
        root: Path, method: dict[str, Any],
    ) -> dict[str, Any]:
        from .scientific_architecture_discovery import discover_architecture

        return discover_architecture(root, method)
    @classmethod
    def _contract_context(cls, root: Path) -> dict[str, Any]:
        from .scientific_asset_contract import build_contract_context

        return build_contract_context(
            root, cls._implementation_architecture_blueprint
        )
    @staticmethod
    def _primary_group(
        records: list[ResultRecord],
    ) -> tuple[str, str, list[ResultRecord]]:
        from .scientific_aggregation import primary_group

        return primary_group(records)
    @staticmethod
    def _comparison_unit_count(records: list[ResultRecord]) -> int:
        from .scientific_aggregation import comparison_unit_count

        return comparison_unit_count(records)
    @staticmethod
    def _aggregate(records: list[ResultRecord]) -> list[dict[str, str]]:
        from .scientific_aggregation import aggregate_records

        return aggregate_records(records)
    def _attach_secondary_measure(
        self,
        rows: list[dict[str, str]],
        records: list[ResultRecord],
        primary_metric: str,
    ) -> None:
        """Attach one observed complementary endpoint for 2-D scientific plots."""
        if not rows:
            return
        groups: dict[str, list[ResultRecord]] = {}
        for record in records:
            if record.metric == primary_metric:
                continue
            groups.setdefault(record.metric, []).append(record)
        if not groups:
            return
        row_keys = {
            (
                str(row.get("method") or ""),
                str(row.get("condition_name") or ""),
                str(row.get("condition_value") or ""),
            )
            for row in rows
        }
        candidates: list[tuple[int, int, str, list[dict[str, str]]]] = []
        for metric, values in groups.items():
            aggregates = self._aggregate(values)
            aggregate_keys = {
                (
                    str(row.get("method") or ""),
                    str(row.get("condition_name") or ""),
                    str(row.get("condition_value") or ""),
                )
                for row in aggregates
            }
            overlap = len(row_keys & aggregate_keys)
            preference = int(bool(re.search(
                r"(?:latency|throughput|cost|energy|memory|fdr|q value|"
                r"adjusted p|net benefit|specificity|sensitivity|error)",
                metric,
                flags=re.IGNORECASE,
            )))
            if overlap:
                candidates.append((overlap, preference, metric, aggregates))
        if not candidates:
            return
        _, _, metric, aggregates = max(
            candidates,
            key=lambda item: (item[0], item[1], len(item[3])),
        )
        by_key = {
            (
                str(row.get("method") or ""),
                str(row.get("condition_name") or ""),
                str(row.get("condition_value") or ""),
            ): row
            for row in aggregates
        }
        for row in rows:
            key = (
                str(row.get("method") or ""),
                str(row.get("condition_name") or ""),
                str(row.get("condition_value") or ""),
            )
            secondary = by_key.get(key)
            if not secondary:
                continue
            row["secondary_metric"] = metric
            row["secondary_mean"] = str(secondary.get("mean") or "")
            row["secondary_unit"] = str(secondary.get("unit") or "")

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        content = buffer.getvalue().encode("utf-8-sig")
        if path.is_file() and path.read_bytes() == content:
            return
        atomic_write_bytes(path, content)

    def build_plan(
        self, project_path: str | Path, *, experiment_requested: bool,
        requested_evidence_mode: str = "", illustration_mode: str = "auto",
        direction: str = "", target_venue: str = "",
        research_family: str = "", study_archetype: str = "",
    ) -> dict[str, Any]:
        from .scientific_asset_plan import build_asset_plan

        return build_asset_plan(
            self, project_path, experiment_requested=experiment_requested,
            requested_evidence_mode=requested_evidence_mode,
            illustration_mode=illustration_mode, direction=direction,
            target_venue=target_venue, research_family=research_family,
            study_archetype=study_archetype,
            archetype_plot_roles=ARCHETYPE_PLOT_ROLES,
        )
    def load(self, project_path: str | Path) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        return _json(root / self.plan_relative_path)


scientific_asset_service = ScientificAssetService()
