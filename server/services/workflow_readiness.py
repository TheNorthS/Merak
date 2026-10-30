"""Classify a finished workflow without conflating execution with submission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .simulation_policy import (
    simulation_manifest_contract_issues,
)
from .review_readiness import review_readiness_issues
from .paper_build_readiness import paper_build_issues
from .workflow_inputs import artifact_state
from .workflow_readiness_assessment import assess_workflow_readiness


READINESS_SCHEMA_VERSION = 8
EMPIRICAL_EVIDENCE_MODES = {
    "executed",
    "existing_results",
    "secondary_analysis",
    "synthetic_preview",
}

# Slides are useful delivery artifacts, but they are not required to submit a
# manuscript. Every other canonical research phase must have an accepted gate.
SUBMISSION_PHASES = (
    "lit",
    "idea",
    "novelty",
    "exp-design",
    "exp-run",
    "results",
    "narrative",
    "figure",
    "paper",
    "review",
    "audit",
    "compile",
)

READINESS_INPUT_PATHS = (
    "experiments/results/simulated/SIMULATION_MANIFEST.json",
    "experiments/results/simulated",
    "figures/SCIENTIFIC_ASSET_PLAN.json",
    "figures/FIGURE_MANIFEST.json",
    "figures/plots",
    "figures/diagrams",
    "figures/assets",
    "figures/ai_generated",
    "paper/PAPER_BUILD.json",
    "paper/PROOF_AUDIT.json",
    "paper/main.pdf",
    "paper/main.tex",
    "paper/sections",
    "paper/tables",
    "paper/references.bib",
    "review-stage/REVIEW_STATE.json",
    "audit-results/AUDIT_RESULTS.json",
    "audit-results/AUDIT_BUILD.json",
    "experiments/results",
    "experiments/logs",
    ".merak/execution_events.jsonl",
    ".merak/evidence-imports",
    ".merak/experiments",
    ".merak/model-api-reviewer",
    "review-stage/pdf-layout",
    "slides",
)


SUBMISSION_ASSURANCE_LEVELS = {
    "conference-ready",
    "submission",
}


def validate_submission_start(
    node_ids: list[str] | tuple[str, ...],
    assurance: str,
    options: dict[str, Any] | None,
    *,
    resume: bool = False,
) -> list[str]:
    """Validate whether a requested evidence track may start.

    A selected deterministic benchmark may intentionally exercise the full
    submission-assurance manuscript pipeline. Its generator/provenance remains
    distinct in machine-side metadata, while the rendered manuscript follows
    the normal submission contract.
    """
    normalized_assurance = str(assurance or "draft").strip().casefold()
    if normalized_assurance not in SUBMISSION_ASSURANCE_LEVELS:
        return []

    supplied = options if isinstance(options, dict) else {}
    requested_run = supplied.get("run_experiment") is True
    execution_enabled = requested_run and (
        resume or "exp-run" in {str(item) for item in node_ids}
    )
    evidence_mode = str(
        supplied.get("non_experiment_evidence_mode") or "design_only"
    ).strip().casefold()
    imported = evidence_mode in {"existing_results", "secondary_analysis"}
    synthetic_preview = evidence_mode == "synthetic_preview"
    if execution_enabled or imported or synthetic_preview:
        return []
    return [
        "submission assurance requires an executed exp-run phase or a "
        "hash-verified existing_results/secondary_analysis import; "
        "design_only is not a complete manuscript evidence track"
    ]


def _read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = _read_json_value(path)
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _accepted(phase: Any) -> bool:
    return (
        isinstance(phase, dict)
        and str(phase.get("status") or "").casefold()
        in {"accepted", "completed"}
    )


class WorkflowReadinessService:
    """Build a durable delivery verdict from independently persisted evidence."""

    report_path = Path(".merak") / "DELIVERY_STATUS.json"
    schema_version = READINESS_SCHEMA_VERSION

    @staticmethod
    def _simulation_package_issues(
        root: Path,
    ) -> tuple[list[str], dict[str, Any]]:
        manifest_path = (
            root / "experiments" / "results" / "simulated"
            / "SIMULATION_MANIFEST.json"
        )
        manifest = _read_json(manifest_path)
        issues = simulation_manifest_contract_issues(manifest)
        checked_files = 0
        data_records = manifest.get("data_files") or []
        data_records = data_records if isinstance(data_records, list) else []
        declared_paths: list[str] = []
        for item in data_records:
            if not isinstance(item, dict):
                issues.append("data_files contains a non-object record")
                continue
            relative = str(item.get("path") or "").strip().replace("\\", "/")
            if relative:
                declared_paths.append(relative)
            expected = str(item.get("sha256") or "").strip().casefold()
            try:
                candidate = (root / relative).resolve() if relative else root
            except (OSError, RuntimeError, ValueError):
                issues.append(f"data file path is invalid: {relative or '(missing path)'}")
                continue
            if (
                not relative.startswith("experiments/results/simulated/")
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
                or len(expected) != 64
                or _sha256_file(candidate) != expected
            ):
                issues.append(f"data file binding is invalid: {relative or '(missing path)'}")
                continue
            checked_files += 1
        if len(set(declared_paths)) != len(declared_paths):
            issues.append("simulation package declares duplicate data file paths")
        # Seven semantic result roles are mandatory, but renderer v7 also
        # writes a claim-specific evidence table.  Readiness previously
        # hard-coded exactly seven files and therefore rejected every current
        # valid current eight-file package.
        expected_bindings = sum(
            1 for item in data_records
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        )
        if checked_files != expected_bindings:
            issues.append(
                "simulation package does not bind every declared current data file"
            )
        if expected_bindings < 7:
            issues.append("simulation package binds fewer than seven result data files")
        return list(dict.fromkeys(issues)), {
            "valid": not issues,
            "schema": int(manifest.get("schema") or 0),
            "primary_metric": str(manifest.get("primary_metric") or ""),
            "metric_direction": str(manifest.get("metric_direction") or ""),
            "bound_data_file_count": checked_files,
        }

    @staticmethod
    def _paper_build_issues(
        root: Path,
        paper_build: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        return paper_build_issues(root, paper_build)
    @staticmethod
    def _review_issues(
        root: Path,
        review_state: dict[str, Any],
        *,
        run_id: str,
        evidence_mode: str,
    ) -> tuple[list[str], dict[str, Any]]:
        return review_readiness_issues(
            root,
            review_state,
            run_id=run_id,
            evidence_mode=evidence_mode,
        )
    @staticmethod
    def _audit_issues(
        root: Path,
        *,
        run_id: str,
        evidence_mode: str,
        executor_model: str = "",
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        from ..workflows.review_audit import validate_audit_bundle

        bundle = validate_audit_bundle(
            root,
            run_id=run_id,
            evidence_mode=evidence_mode,
            executor_model=executor_model,
        )
        entries = bundle.get("entries")
        entries = entries if isinstance(entries, list) else []
        issues = list(bundle.get("issues") or [])
        return issues, entries, {
            "valid": bundle.get("valid") is True,
            "accepted": bundle.get("accepted") is True,
            "source_bundle_sha256": bundle.get("source_bundle_sha256") or "",
            "source_count": int(bundle.get("source_count") or 0),
            "layers": list(bundle.get("layers") or []),
            "proof": dict(bundle.get("proof") or {}),
            "scientific_verdicts": list(
                bundle.get("scientific_verdicts") or []
            ),
            "verdicts": list(bundle.get("verdicts") or []),
            "blocking_verdicts": list(bundle.get("blocking_verdicts") or []),
            "blocking_issues": list(bundle.get("blocking_issues") or []),
            "advisories": list(bundle.get("advisories") or []),
            "warning_count": int(bundle.get("warning_count") or 0),
            "audit_runtime_signature": str(
                bundle.get("audit_runtime_signature") or ""
            ),
            "reviewer_route_sha256": str(
                bundle.get("reviewer_route_sha256") or ""
            ),
        }

    def input_fingerprint(
        self,
        project_path: str | Path,
        run_state: dict[str, Any] | None,
    ) -> str:
        """Hash every durable fact that can change the submission verdict."""
        root = Path(project_path).expanduser().resolve()
        state = run_state if isinstance(run_state, dict) else {}
        config = state.get("config")
        config = config if isinstance(config, dict) else {}
        options = config.get("options")
        options = options if isinstance(options, dict) else {}
        phases = state.get("phases")
        phases = phases if isinstance(phases, dict) else {}
        try:
            from ..workflows.review_audit import (
                AUDIT_LAYER_SKILLS,
                audit_policy_sha256,
                audit_reviewer_route,
                audit_reviewer_route_sha256,
                audit_runtime_signature,
            )

            current_route = audit_reviewer_route()
            audit_contract = {
                "runtime_signature": audit_runtime_signature(),
                "reviewer_route_sha256": audit_reviewer_route_sha256(
                    current_route
                ),
                "policy_sha256": {
                    str(layer): audit_policy_sha256(skill_name)
                    for layer, skill_name in AUDIT_LAYER_SKILLS.items()
                },
            }
        except Exception as exc:
            audit_contract = {
                "error": type(exc).__name__,
            }
        payload = {
            "schema": self.schema_version,
            "run_id": str(state.get("run_id") or ""),
            "assurance": str(config.get("assurance") or ""),
            "evidence_request": {
                "delivery_goal": options.get("delivery_goal", "submission_candidate"),
                "run_experiment": options.get("run_experiment") is True,
                "non_experiment_evidence_mode": str(
                    options.get("non_experiment_evidence_mode") or ""
                ),
            },
            "audit_contract": audit_contract,
            "phases": {
                str(phase_id): {
                    "status": str(phase.get("status") or ""),
                    "verdict_id": str(phase.get("verdict_id") or ""),
                    "reviewer": str(phase.get("reviewer") or ""),
                }
                for phase_id, phase in sorted(phases.items())
                if isinstance(phase, dict)
            },
            "artifacts": {
                relative: artifact_state(root / relative, max_files=5000)
                for relative in READINESS_INPUT_PATHS
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def needs_refresh(
        self,
        project_path: str | Path,
        run_state: dict[str, Any] | None,
    ) -> bool:
        state = run_state if isinstance(run_state, dict) else {}
        completion = state.get("completion")
        if not isinstance(completion, dict):
            return True
        if int(completion.get("schema") or 0) != self.schema_version:
            return True
        return str(completion.get("readiness_input_sha256") or "") != (
            self.input_fingerprint(project_path, state)
        )

    def assess(
        self,
        project_path: str | Path,
        run_state: dict[str, Any] | None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        return assess_workflow_readiness(
            self,
            project_path,
            run_state,
            persist=persist,
            submission_phases=SUBMISSION_PHASES,
            empirical_modes=EMPIRICAL_EVIDENCE_MODES,
        )


workflow_readiness_service = WorkflowReadinessService()
