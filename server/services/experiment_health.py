"""Deterministic health analysis for local and remote experiment logs."""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_LOSS_PATTERN = re.compile(
    rf"(?i)(?P<name>(?:train[/_. -]?)?(?:total[/_. -]?)?loss)\s*[:=]\s*(?P<value>{_NUMBER}|nan|inf|-inf)"
)
_STEP_PATTERN = re.compile(r"(?i)(?:global[_ /-]?)?(?:step|epoch)\s*[:=]\s*(\d+)")
_OOM_PATTERN = re.compile(
    r"(?i)(cuda\s+out\s+of\s+memory|outofmemoryerror|cudnn_status_alloc_failed|resource exhausted.*memory)"
)
_FATAL_PATTERN = re.compile(
    r"(?i)(segmentation fault|floating point exception|nccl.*(?:error|failed)|fatal error|unhandled exception)"
)


@dataclass(slots=True)
class HealthPolicy:
    """Monitoring thresholds which are persisted with every run."""

    startup_grace_seconds: int = 120
    stall_timeout_seconds: int = 300
    gpu_idle_threshold_percent: int = 5
    gpu_idle_consecutive_checks: int = 3
    zero_loss_epsilon: float = 1e-12
    zero_loss_consecutive_points: int = 3
    zero_loss_min_points: int = 5
    divergence_factor: float = 8.0
    divergence_consecutive_points: int = 3
    plateau_window: int = 12
    plateau_relative_change: float = 0.002
    auto_stop_kinds: tuple[str, ...] = (
        "oom",
        "non_finite_loss",
        "loss_collapse",
        "loss_divergence",
        "fatal_runtime_error",
        "stalled_and_gpu_idle",
    )


@dataclass(slots=True)
class HealthFinding:
    kind: str
    severity: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    @property
    def requires_stop(self) -> bool:
        return self.severity == "critical"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExperimentHealthMonitor:
    """Parse streaming logs and detect conditions which invalidate a run.

    The monitor only recommends stopping. The runtime owns process control,
    artifact collection, and retry/approval policy.
    """

    def __init__(self, policy: HealthPolicy | None = None, started_at: float | None = None) -> None:
        self.policy = policy or HealthPolicy()
        self.started_at = started_at or time.time()
        self.last_log_at = self.started_at
        self.losses: list[dict[str, float | int | None]] = []
        self.latest_metrics: dict[str, Any] = {}
        self.gpu_idle_checks = 0
        self._seen: set[str] = set()
        self._buffer = ""

    def ingest(self, chunk: str, now: float | None = None) -> list[HealthFinding]:
        now = now or time.time()
        if not chunk:
            return []
        self.last_log_at = now
        text = self._buffer + chunk
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._buffer = lines.pop()
        else:
            self._buffer = ""

        findings: list[HealthFinding] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            findings.extend(self._inspect_line(line, now))
        findings.extend(self._inspect_loss_dynamics(now))
        return self._deduplicate(findings)

    def flush(self, now: float | None = None) -> list[HealthFinding]:
        if not self._buffer:
            return []
        buffered, self._buffer = self._buffer, ""
        now = now or time.time()
        findings = self._inspect_line(buffered.strip(), now)
        findings.extend(self._inspect_loss_dynamics(now))
        return self._deduplicate(findings)

    def heartbeat(
        self,
        *,
        running: bool,
        gpu_utilization: Iterable[int | float] | None = None,
        now: float | None = None,
    ) -> list[HealthFinding]:
        now = now or time.time()
        gpu_values = [float(value) for value in (gpu_utilization or [])]
        if gpu_values and all(value < self.policy.gpu_idle_threshold_percent for value in gpu_values):
            self.gpu_idle_checks += 1
        elif gpu_values:
            self.gpu_idle_checks = 0

        if not running or now - self.started_at < self.policy.startup_grace_seconds:
            return []

        silent_for = now - self.last_log_at
        if silent_for < self.policy.stall_timeout_seconds:
            return []

        if self.gpu_idle_checks >= self.policy.gpu_idle_consecutive_checks:
            return self._deduplicate([HealthFinding(
                kind="stalled_and_gpu_idle",
                severity="critical",
                message="Training log is stalled and every observed GPU is idle.",
                evidence={
                    "silent_seconds": round(silent_for, 1),
                    "gpu_utilization": gpu_values,
                    "idle_checks": self.gpu_idle_checks,
                },
                observed_at=now,
            )])

        return self._deduplicate([HealthFinding(
            kind="log_stalled",
            severity="warning",
            message="No new training log output within the configured stall window.",
            evidence={"silent_seconds": round(silent_for, 1), "gpu_utilization": gpu_values},
            observed_at=now,
        )])

    def should_stop(self, findings: Iterable[HealthFinding]) -> bool:
        stop_kinds = set(self.policy.auto_stop_kinds)
        return any(item.severity == "critical" and item.kind in stop_kinds for item in findings)

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy": asdict(self.policy),
            "started_at": self.started_at,
            "last_log_at": self.last_log_at,
            "latest_metrics": self.latest_metrics,
            "loss_history": self.losses[-100:],
            "gpu_idle_checks": self.gpu_idle_checks,
        }

    def _inspect_line(self, line: str, now: float) -> list[HealthFinding]:
        findings: list[HealthFinding] = []
        if _OOM_PATTERN.search(line):
            findings.append(HealthFinding(
                "oom", "critical", "CUDA/device memory exhaustion detected.",
                {"line": line[-1000:]}, now,
            ))
        if _FATAL_PATTERN.search(line):
            findings.append(HealthFinding(
                "fatal_runtime_error", "critical", "A fatal runtime error was reported.",
                {"line": line[-1000:]}, now,
            ))

        metric_payload = self._extract_json_metrics(line)
        if metric_payload:
            self.latest_metrics.update(metric_payload)
            step = self._metric_step(metric_payload)
            for key, value in self._flatten(metric_payload).items():
                if "loss" not in key.lower():
                    continue
                finding = self._record_loss(value, step, key, now)
                if finding:
                    findings.append(finding)
        else:
            step_match = _STEP_PATTERN.search(line)
            step = int(step_match.group(1)) if step_match else None
            for match in _LOSS_PATTERN.finditer(line):
                finding = self._record_loss(match.group("value"), step, match.group("name"), now)
                if finding:
                    findings.append(finding)
        return findings

    @staticmethod
    def _extract_json_metrics(line: str) -> dict[str, Any]:
        candidates = [line]
        first, last = line.find("{"), line.rfind("}")
        if first >= 0 and last > first:
            candidates.append(line[first:last + 1])
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                flattened.update(ExperimentHealthMonitor._flatten(item, path))
            else:
                flattened[path] = item
        return flattened

    @staticmethod
    def _metric_step(metrics: dict[str, Any]) -> int | None:
        flattened = ExperimentHealthMonitor._flatten(metrics)
        for key, value in flattened.items():
            if key.lower().split(".")[-1] not in {"step", "global_step", "epoch"}:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _record_loss(
        self,
        raw_value: Any,
        step: int | None,
        name: str,
        now: float,
    ) -> HealthFinding | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return HealthFinding(
                "non_finite_loss", "critical", "Loss became NaN or infinite.",
                {"metric": name, "value": str(raw_value), "step": step}, now,
            )
        self.losses.append({"value": value, "step": step, "time": now, "metric": name})
        return None

    def _inspect_loss_dynamics(self, now: float) -> list[HealthFinding]:
        policy = self.policy
        values = [float(item["value"]) for item in self.losses]
        findings: list[HealthFinding] = []
        if len(values) >= policy.zero_loss_min_points:
            tail = values[-policy.zero_loss_consecutive_points:]
            if len(tail) == policy.zero_loss_consecutive_points and all(abs(value) <= policy.zero_loss_epsilon for value in tail):
                findings.append(HealthFinding(
                    "loss_collapse", "critical",
                    "Loss is exactly or nearly zero for consecutive observations; this often indicates leakage, an empty mask, or a broken objective.",
                    {"recent_losses": tail, "points_seen": len(values)}, now,
                ))

        required = max(6, policy.divergence_consecutive_points * 2)
        if len(values) >= required:
            baseline_values = [abs(value) for value in values[:3] if abs(value) > policy.zero_loss_epsilon]
            recent = values[-policy.divergence_consecutive_points:]
            if baseline_values:
                baseline = statistics.median(baseline_values)
                threshold = max(baseline * policy.divergence_factor, baseline + 1.0)
                if all(value > threshold for value in recent) and all(a <= b for a, b in zip(recent, recent[1:])):
                    findings.append(HealthFinding(
                        "loss_divergence", "critical", "Loss is diverging beyond the configured baseline factor.",
                        {"baseline": baseline, "threshold": threshold, "recent_losses": recent}, now,
                    ))

        if len(values) >= policy.plateau_window:
            window = values[-policy.plateau_window:]
            scale = max(abs(window[0]), policy.zero_loss_epsilon)
            relative_change = abs(window[0] - window[-1]) / scale
            if relative_change <= policy.plateau_relative_change:
                findings.append(HealthFinding(
                    "loss_plateau", "warning", "Loss has changed very little over the monitoring window.",
                    {"window": policy.plateau_window, "relative_change": relative_change}, now,
                ))
        return findings

    def _deduplicate(self, findings: Iterable[HealthFinding]) -> list[HealthFinding]:
        unique: list[HealthFinding] = []
        for finding in findings:
            key = finding.kind
            if key in self._seen:
                continue
            self._seen.add(key)
            unique.append(finding)
        return unique
