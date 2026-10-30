"""Frozen prospective CSFS-v1 constants, not observations or launch permission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_ID = "CSFS-v1"
CANONICAL_CHANNELS = (
    "Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2",
    "F7", "F8", "T3", "T4", "T5", "T6", "Fz", "Cz", "Pz",
)
SEEDS = (13, 42, 73, 101, 202)
METHOD_IDS = (
    "csfs", "bendr_context", "masked_latent", "channel_only", "frequency_only",
    "full_latent", "no_private", "shuffled_pair", "random_init",
)
VIEW_KEYS = ("a_low", "a_high", "b_low", "b_high")
SAMPLING_RATE_HZ = 256
WINDOW_SECONDS, STRIDE_SECONDS = 30, 15
WINDOW_SAMPLES, STRIDE_SAMPLES = 7680, 3840
MIN_CHANNELS, C3_MIN_CHANNELS = 8, 16
PREPROCESS_BAND, LOW_BAND, HIGH_BAND = (0.5, 45.0), (1.0, 30.0), (8.0, 40.0)
FILTER_ORDER = 4
MODEL_WIDTHS, KERNEL_SIZE, DROPOUT = (64, 128, 192, 192), 15, 0.10
EMBEDDING_DIM, SHARED_DIM, PRIVATE_DIM = 192, 128, 64
TEMPERATURE, PRIVATE_WEIGHT = 0.20, 0.05
PRETRAIN_WINDOWS, BATCH_SIZE, CHECKPOINT_WINDOWS = 100000, 32, 1000
SELECTION_PROBE_UPDATES, FINAL_PROBE_UPDATES = 1000, 10000
LEARNING_RATE, WEIGHT_DECAY, GRAD_NORM_LIMIT = 3e-4, 0.01, 1.0
PATIENCE, MIN_DELTA = 10, 0.001
MAX_NONFINITE, MAX_OOM, HEARTBEAT_SECONDS = 1, 2, 900
BOOTSTRAP_RESAMPLES, SIGNFLIP_RESAMPLES = 10000, 100000
HOLM_ALPHA, EQUIVALENCE_MARGIN, IN_DOMAIN_MARGIN = 0.05, 0.01, 0.02
REGIONS = {
    "frontal": ("Fp1", "Fp2", "F3", "F4", "F7", "F8", "Fz"),
    "central": ("C3", "C4", "Cz", "T3", "T4"),
    "posterior": ("P3", "P4", "Pz", "O1", "O2", "T5", "T6"),
}


class ProtocolError(ValueError):
    """A design, provenance, eligibility or execution boundary is unmet."""


@dataclass(frozen=True)
class ExecutionResources:
    """Environment ceilings declared before launch, not tuned to outcomes."""

    device: str
    wall_time_seconds: int
    peak_memory_bytes: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExecutionResources":
        if (not isinstance(value, Mapping) or set(value) != {
                "device", "wall_time_seconds", "peak_memory_bytes"}
                or value.get("device") not in {"cpu", "cuda"}
                or any(type(value.get(key)) is not int or value[key] <= 0
                       for key in ("wall_time_seconds", "peak_memory_bytes"))):
            raise ProtocolError("Execution requires device, wall-time and memory ceilings")
        return cls(**value)


def require_registered_config(config: Mapping[str, Any]) -> None:
    """Reject changed scientific budgets; no retired epoch-based compatibility."""
    if not isinstance(config, Mapping):
        raise ProtocolError("CSFS-v1 configuration must be an object")
    expected = registered_configuration()
    if config.get("protocol") != expected:
        raise ProtocolError("Configuration differs from the frozen CSFS-v1 operational protocol")


def registered_configuration() -> dict[str, Any]:
    """Return the exact prospective values, without experimental observations."""
    return {
        "id": PROTOCOL_ID, "seeds": list(SEEDS), "methods": list(METHOD_IDS),
        "pretraining_windows": PRETRAIN_WINDOWS, "batch_size": BATCH_SIZE,
        "checkpoint_windows": CHECKPOINT_WINDOWS,
        "selection_probe_updates": SELECTION_PROBE_UPDATES,
        "final_probe_updates": FINAL_PROBE_UPDATES,
        "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY,
        "gradient_norm_limit": GRAD_NORM_LIMIT,
    }


def require_execution_authorization(config: Mapping[str, Any], *, allow_execution: bool) -> ExecutionResources:
    """CLI and configuration must both consent; source readiness is not consent."""
    require_registered_config(config)
    research, execution = config.get("research_contract"), config.get("execution")
    if (allow_execution is not True or not isinstance(research, Mapping)
            or not isinstance(execution, Mapping) or research.get("execution_authorized") is not True
            or execution.get("execution_prohibited_in_this_stage") is not False):
        raise ProtocolError("Research execution is not authorized")
    return ExecutionResources.from_mapping(execution.get("resources"))


def owned_output_directory(root: Path, relative: str) -> Path:
    """Actual execution cannot overwrite frozen simulated or original results."""
    root = root.resolve(strict=True)
    candidate, path = root / relative, (root / relative).resolve()
    if (relative != "experiments/results/executed" or not path.is_relative_to(root)
            or candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents)):
        raise ProtocolError("Outputs require separate owned experiments/results/executed directory")
    return path
