"""Persist deterministic diagnostics for one managed experiment attempt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text


def write_diagnosis(
    spec: Any,
    store: Any,
    attempt_number: int,
    state: str,
    anomalies: list[Any],
    error: str,
    log_path: str,
    *,
    utc_now: Any,
) -> Path:
    attempt_dir = store.root / f"attempt-{attempt_number:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    recommendations = _recommendations([item.kind for item in anomalies])
    payload = {
        "schema_version": 1,
        "run_id": spec.run_id,
        "attempt": attempt_number,
        "backend": spec.normalized_backend(),
        "state": state,
        "error": error,
        "log_path": log_path,
        "anomalies": [item.to_dict() for item in anomalies],
        "recommendations": recommendations,
        "retry_contract": {
            "automatic_code_edits": False,
            "requires_user_approval_for_code_or_scientific_config_changes": True,
            "new_attempt_required": True,
            "preserve_failed_attempt": True,
        },
        "created_at": utc_now(),
    }
    diagnosis_path = attempt_dir / "diagnosis.json"
    atomic_write_json(diagnosis_path, payload)
    atomic_write_text(
        attempt_dir / "DIAGNOSIS.md",
        _diagnosis_markdown(spec, attempt_number, state, error, log_path, anomalies, recommendations),
    )
    return diagnosis_path


def _recommendations(kinds: list[str]) -> list[str]:
    recommendations: list[str] = []
    if "oom" in kinds:
        recommendations.extend([
            "Reduce per-device batch size and compensate with gradient accumulation.",
            "Inspect activation/checkpoint memory before changing the scientific model.",
        ])
    if "non_finite_loss" in kinds or "loss_divergence" in kinds:
        recommendations.extend([
            "Inspect the first non-finite step, learning rate, gradient norm, AMP scaler, and input ranges.",
            "Re-run a deterministic mini-batch with anomaly detection before a full retry.",
        ])
    if "loss_collapse" in kinds:
        recommendations.extend([
            "Audit train/validation subject separation and label leakage.",
            "Check empty masks, zero denominators, target construction, and whether the objective is bypassed.",
        ])
    if "stalled_and_gpu_idle" in kinds or "log_stalled" in kinds:
        recommendations.extend([
            "Inspect DataLoader workers, remote storage latency, deadlocks, and process descendants.",
            "Reproduce with num_workers=0 and a bounded data sample before retrying remotely.",
        ])
    if not recommendations:
        recommendations.extend([
            "Inspect the preserved log tail and exact exit code.",
            "Run the smallest deterministic preflight command before scheduling another paid run.",
        ])
    return list(dict.fromkeys(recommendations))


def _diagnosis_markdown(
    spec: Any,
    attempt: int,
    state: str,
    error: str,
    log_path: str,
    anomalies: list[Any],
    recommendations: list[str],
) -> str:
    lines = [
        f"# Experiment Diagnosis: {spec.run_id}", "",
        f"- Attempt: {attempt}",
        f"- Backend: {spec.normalized_backend()}",
        f"- State: {state}",
        f"- Error: {error or '(none)'}",
        f"- Preserved log: {log_path or '(not available)'}",
        "", "## Findings",
    ]
    lines.extend(
        f"- [{item.severity}] {item.kind}: {item.message}" for item in anomalies
    )
    if not anomalies:
        lines.append("- No structured anomaly was parsed; inspect the process error and log tail.")
    lines.extend(["", "## Next Checks"])
    lines.extend(f"- {item}" for item in recommendations)
    lines.extend([
        "",
        "Code or scientific configuration changes must be submitted as a separate approval proposal. A retry creates a new attempt and never overwrites this evidence.",
    ])
    return "\n".join(lines) + "\n"
