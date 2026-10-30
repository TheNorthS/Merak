"""Recover an attempt's original deadline instead of granting a fresh runtime budget."""

from datetime import datetime
import time


def attempt_record(store, number: int) -> dict:
    return next((item for item in store.load().get("attempts", [])
                 if item.get("attempt") == number), {})


def attempt_started(record: dict) -> float:
    value = record.get("started_at")
    if not value:
        raise ValueError("Experiment attempt lacks its original start time; cannot reset its execution budget")
    try:
        started = datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, OverflowError) as error:
        raise ValueError("Experiment attempt start time is invalid") from error
    if started > time.time() + 5:
        raise ValueError("Experiment attempt start time is in the future")
    return started


def restore_monitor_health(health, saved: dict) -> None:
    """Continue observed metrics and trends without re-reading old log bytes."""
    snapshot = saved.get("health") or {}
    health.latest_metrics.update(snapshot.get("latest_metrics") or {})
    health.losses = list(snapshot.get("loss_history") or [])[-100:]
    health.gpu_idle_checks = max(0, int(snapshot.get("gpu_idle_checks") or 0))
    health.started_at = attempt_started(saved)
    if snapshot.get("last_log_at") is not None:
        health.last_log_at = float(snapshot["last_log_at"])
