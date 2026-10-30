"""Hash-bound, current-identity CSFS-v1 checkpoint resume contracts.

Only a direct owned checkpoint with known complete state is deserialized, using
weights_only=True and CPU mapping. Resuming never changes science, budgets,
resource ceilings or acceptance status; it recreates the same seeded sampler.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import hashlib
import io
import math
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Iterator

from .execution_safety import RNG_KEYS, require_cpu_snapshot
from .protocol import (CHECKPOINT_WINDOWS, METHOD_IDS, PRETRAIN_WINDOWS, PROTOCOL_ID, SEEDS,
                       ExecutionResources, ProtocolError)
from .training_policy import SelectionPolicy


@dataclass(frozen=True)
class CheckpointIdentity:
    config_sha256: str
    source_sha256: str
    corpus_sha256: str
    fold_sha256: str
    normalization_sha256: str
    seed: int
    method_id: str
    target_id: str
    fit_role: str
    resources: ExecutionResources
    protocol_id: str = PROTOCOL_ID


CHECKPOINT_KEYS = frozenset({"schema", "identity", "windows", "model", "optimizer", "best_model",
                            "policy", "rng", "sampler", "anomaly", "resources_elapsed_seconds", "saved_at_unix"})
POLICY_KEYS = frozenset(SelectionPolicy().__dict__)


def _identity(identity: CheckpointIdentity) -> dict[str, Any]:
    payload = asdict(identity)
    for key in ("config_sha256", "source_sha256", "corpus_sha256", "fold_sha256", "normalization_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", payload[key]):
            raise ProtocolError("Checkpoint identity requires complete current source/config/data/fold hashes")
    if (identity.protocol_id != PROTOCOL_ID or type(identity.seed) is not int or identity.seed not in SEEDS
            or identity.method_id not in METHOD_IDS or not identity.target_id
            or identity.fit_role not in {"source_training", "target_local_training"}):
        raise ProtocolError("Checkpoint has an undeclared method/seed/fitting protocol")
    ExecutionResources.from_mapping(payload["resources"])
    return payload


def _policy(payload: dict[str, Any], windows: int) -> None:
    if not isinstance(payload, dict) or set(payload) != POLICY_KEYS or not isinstance(payload["events"], list):
        raise ProtocolError("Resume checkpoint lacks complete selection/stopping/budget policy state")
    replay = SelectionPolicy()
    stopped = False
    for event in payload["events"]:
        if not isinstance(event, dict) or stopped:
            raise ProtocolError("Resume selection events are malformed or extend past the stopping rule")
        stopped = replay.observe(event["windows"], event["score"], event["probe_updates"])
    if payload != replay.__dict__ or payload["windows"] != windows or payload["final_probe_updates"] != 0:
        raise ProtocolError("Checkpoint selection state differs from its exact event history or spent final-probe budget")


def validate_resume_checkpoint(payload: dict[str, Any], identity: CheckpointIdentity) -> dict[str, Any]:
    """Reject incomplete/stale resume records before loading model or optimizer state."""
    if (not isinstance(payload, dict) or set(payload) != CHECKPOINT_KEYS or payload.get("schema") != 1
            or payload.get("identity") != _identity(identity)):
        raise ProtocolError("Resume checkpoint has stale, foreign or unsupported protocol identity")
    windows = payload["windows"]
    if type(windows) is not int or not 0 < windows <= PRETRAIN_WINDOWS or windows % CHECKPOINT_WINDOWS:
        raise ProtocolError("Resume windows must be a completed registered checkpoint within the frozen budget")
    if any(not isinstance(payload[key], dict) or not payload[key] for key in ("model", "optimizer", "best_model")):
        raise ProtocolError("Resume checkpoint lacks full model, optimizer or selected-best model state")
    _policy(payload["policy"], windows)
    rng, sampler, anomaly = payload["rng"], payload["sampler"], payload["anomaly"]
    if not isinstance(rng, dict) or set(rng) != RNG_KEYS or any(rng[key] is None for key in ("python", "numpy", "torch", "objective")):
        raise ProtocolError("Resume checkpoint lacks complete Python/NumPy/Torch/objective/CUDA RNG states")
    if (not isinstance(sampler, dict) or set(sampler) != {"seed", "cursor", "window_budget", "sampling_role"}
            or sampler != {"seed": identity.seed, "cursor": windows, "window_budget": PRETRAIN_WINDOWS, "sampling_role": "pretrain"}):
        raise ProtocolError("Resume sampler differs from its exact seeded consumed-window stream")
    elapsed = payload["resources_elapsed_seconds"]
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed)
            or not 0 <= elapsed < identity.resources.wall_time_seconds):
        raise ProtocolError("Checkpoint elapsed resources are invalid or already exhausted")
    saved = payload["saved_at_unix"]
    if isinstance(saved, bool) or not isinstance(saved, (int, float)) or not math.isfinite(saved) or saved <= 0:
        raise ProtocolError("Checkpoint lacks its actual persisted wall-clock save time")
    required_anomaly = {"oom_events", "initial_losses", "pathological_losses", "heartbeat_age_seconds"}
    if (not isinstance(anomaly, dict) or set(anomaly) != required_anomaly
            or type(anomaly["oom_events"]) is not int or not 0 <= anomaly["oom_events"] < 2
            or type(anomaly["pathological_losses"]) is not int or not 0 <= anomaly["pathological_losses"] < 50
            or not isinstance(anomaly["initial_losses"], list) or len(anomaly["initial_losses"]) > 20
            or any(not math.isfinite(value) for value in anomaly["initial_losses"])
            or not 0 <= anomaly["heartbeat_age_seconds"] < 900):
        raise ProtocolError("Checkpoint lost anomaly/failure counters or heartbeat resource history")
    require_cpu_snapshot(payload)
    return copy.deepcopy(payload)


def build_resume_checkpoint(
    identity: CheckpointIdentity, *, windows: int, model: dict, optimizer: dict, best_model: dict,
    policy: dict, rng: dict, sampler: dict, anomaly: dict, resources_elapsed_seconds: float,
    saved_at_unix: float,
) -> dict[str, Any]:
    """Build only a complete actual checkpoint; no completion or acceptance stamps."""
    payload = {"schema": 1, "identity": _identity(identity), "windows": windows, "model": model,
               "optimizer": optimizer, "best_model": best_model, "policy": policy, "rng": rng,
               "sampler": sampler, "anomaly": anomaly, "resources_elapsed_seconds": resources_elapsed_seconds,
               "saved_at_unix": saved_at_unix}
    return validate_resume_checkpoint(payload, identity)


def load_bound_checkpoint(
    path: str | Path, expected_sha256: str, identity: CheckpointIdentity, *, owned_attempt_root: Path,
    loader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read owned bytes and verify hash before safe deserialization or state mutation."""
    base, candidate = owned_attempt_root.resolve(strict=True), Path(path)
    resolved = candidate.resolve(strict=True)
    if (resolved.parent != base or resolved.suffix != ".pt" or not resolved.is_file()
            or candidate.is_symlink() or resolved.stat().st_nlink > 1
            or any(parent.is_symlink() for parent in candidate.parents)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)):
        raise ProtocolError("Checkpoint must be an exact direct unlinked owned attempt artifact")
    raw = resolved.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ProtocolError("Checkpoint bytes differ from their persisted immutable artifact binding")
    if loader is None:
        import torch

        loader = torch.load
    payload = loader(io.BytesIO(raw), map_location="cpu", weights_only=True)
    try:
        return validate_resume_checkpoint(payload, identity)
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError("Loaded checkpoint does not satisfy the complete current resume contract") from error


def resume_seeded_stream(factory: Callable[[], Iterable[Any]], cursor: int) -> Iterator[Any]:
    """Recreate the same registered seed stream and skip exactly consumed windows."""
    if type(cursor) is not int or not 0 <= cursor <= PRETRAIN_WINDOWS:
        raise ProtocolError("Sampler resume cursor is outside the frozen registered window budget")
    stream = iter(factory())
    for _ in range(cursor):
        try:
            next(stream)
        except StopIteration as error:
            raise ProtocolError("Checkpoint cursor exceeds the reproducible registered sampler stream") from error
    return stream


def resumed_resource_origin(clock: Callable[[], float], checkpoint: dict[str, Any], *,
                            wallclock: Callable[[], float] = time.time) -> tuple[float, float]:
    """Carry spent elapsed time and heartbeat age across restarts, never reset ceilings."""
    current = clock()
    downtime = wallclock() - checkpoint["saved_at_unix"]
    if not math.isfinite(downtime) or downtime < 0:
        raise ProtocolError("Resume wall clock predates the exact persisted checkpoint")
    return (current - checkpoint["resources_elapsed_seconds"] - downtime,
            current - checkpoint["anomaly"]["heartbeat_age_seconds"] - downtime)
