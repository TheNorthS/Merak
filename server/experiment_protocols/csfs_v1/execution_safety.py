"""One exact OOM retry after complete CPU-state rollback, never extra budget.

The caller captures actual model/optimizer/gradient/RNG/sampler/protocol state.
Only its explicitly supplied OOM exception type is retryable; arbitrary runtime
errors, nonfinite failures and cancellation propagate without reinterpretation.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, TypeVar

from .protocol import ProtocolError


Result = TypeVar("Result")
STEP_KEYS = frozenset({"model", "optimizer", "gradients", "best_model", "rng", "sampler", "budget", "policy", "anomaly"})
RNG_KEYS = frozenset({"python", "numpy", "torch", "cuda", "objective"})


class StepOOMError(ProtocolError):
    """The registered attempt reached its OOM limit after restoring the failed step."""


def require_cpu_snapshot(value: Any) -> None:
    """Recursively require host-owned snapshot tensors and containers."""
    if isinstance(value, dict):
        for item in value.values():
            require_cpu_snapshot(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            require_cpu_snapshot(item)
    elif hasattr(value, "device"):
        if str(value.device) != "cpu" or getattr(value, "requires_grad", False):
            raise ProtocolError("OOM rollback snapshots require detached CPU tensors")
    elif value is not None and not isinstance(value, (str, bytes, bool, int, float)):
        raise ProtocolError("OOM rollback snapshot contains an undeclared state object")


def _snapshot(snapshot: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    value = snapshot()
    if (not isinstance(value, dict) or set(value) != STEP_KEYS or not isinstance(value["rng"], dict)
            or set(value["rng"]) != RNG_KEYS
            or any(not isinstance(value[key], dict) for key in ("sampler", "budget", "policy", "anomaly"))):
        raise ProtocolError("OOM snapshot must retain complete model, optimizer, gradients, best model, RNG, sampler and budgets")
    require_cpu_snapshot(value)
    return copy.deepcopy(value)


def retry_oom_step(
    operation: Callable[[], Result], snapshot: Callable[[], dict[str, Any]],
    restore: Callable[[dict[str, Any]], None], anomaly: Any, clear_cache: Callable[[], None], *,
    oom_exception: type[Exception],
) -> Result:
    """Restore the exact failed step before retry; two OOM events abort the attempt.

    The state copy must include all consumed-window/update/sampler counters.
    Wall time is not restarted: anomaly.check_time always uses the original clock.
    OOM count survives rollback through anomaly.out_of_memory after restoration.
    """
    if (not isinstance(oom_exception, type) or not issubclass(oom_exception, Exception)
            or oom_exception in {Exception, RuntimeError, MemoryError}):
        raise ProtocolError("Retry requires a specific OOM exception type, not a broad runtime failure")
    before = _snapshot(snapshot)
    for attempt in range(2):
        anomaly.check_time()
        try:
            result = operation()
            anomaly.check_time()
            return result
        except oom_exception as error:
            prior_oom = int(anomaly.oom_events)
            restore(copy.deepcopy(before))
            anomaly.oom_events = prior_oom
            clear_cache()
            try:
                anomaly.out_of_memory()
                anomaly.check_time()
            except ProtocolError as limit:
                raise StepOOMError(str(limit)) from error
            if attempt == 1:
                raise StepOOMError("The second OOM aborted the exact registered step") from error
    raise AssertionError("OOM step terminated without a registered result")
