"""Pure window/probe budget and stopping state; no model updates or execution."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Iterable, Iterator

from .protocol import (
    BATCH_SIZE, CHECKPOINT_WINDOWS, FINAL_PROBE_UPDATES, HEARTBEAT_SECONDS, MAX_OOM,
    MIN_DELTA, PATIENCE, PRETRAIN_WINDOWS, SELECTION_PROBE_UPDATES, ProtocolError,
)


def window_batches(stream: Iterable[Any], *, consumed_windows: int = 0) -> Iterator[tuple[Any, ...]]:
    """Do not cross a 1000-window selection boundary or exceed the frozen budget."""
    if type(consumed_windows) is not int or not 0 <= consumed_windows <= PRETRAIN_WINDOWS or consumed_windows % CHECKPOINT_WINDOWS:
        raise ProtocolError("Resume begins only at a completed registered window checkpoint")
    iterator, consumed = iter(stream), consumed_windows
    while consumed < PRETRAIN_WINDOWS:
        remaining = CHECKPOINT_WINDOWS - consumed % CHECKPOINT_WINDOWS
        size = min(BATCH_SIZE, remaining, PRETRAIN_WINDOWS - consumed)
        values = []
        for _ in range(size):
            try:
                values.append(next(iterator))
            except StopIteration as error:
                raise ProtocolError("Registered source stream ended before its window budget") from error
        consumed += size
        yield tuple(values)


@dataclass
class SelectionPolicy:
    """Earliest best checkpoint, exact fresh probe budgets, ten failed improvements."""

    windows: int = 0
    evaluations: int = 0
    best_score: float = -math.inf
    best_checkpoint: int = 0
    without_improvement: int = 0
    selection_updates: int = 0
    final_probe_updates: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, windows: int, score: float, probe_updates: int) -> bool:
        if (type(windows) is not int or windows != self.windows + CHECKPOINT_WINDOWS
                or windows > PRETRAIN_WINDOWS or not math.isfinite(score) or not 0 <= score <= 1
                or probe_updates != SELECTION_PROBE_UPDATES):
            raise ProtocolError("Checkpoint selection violates the registered windows or fresh probe budget")
        previous = self.best_score
        improved = previous == -math.inf or score >= previous + MIN_DELTA
        if score > self.best_score:
            self.best_score, self.best_checkpoint = score, windows
        self.without_improvement = 0 if improved else self.without_improvement + 1
        self.windows, self.evaluations = windows, self.evaluations + 1
        self.selection_updates += probe_updates
        self.events.append({"windows": windows, "score": score, "probe_updates": probe_updates,
                            "best_checkpoint": self.best_checkpoint, "substantial_improvement": improved})
        return self.without_improvement >= PATIENCE or windows == PRETRAIN_WINDOWS

    def complete_probe(self, updates: int) -> None:
        if type(updates) is not int or updates != FINAL_PROBE_UPDATES or self.final_probe_updates:
            raise ProtocolError("The final frozen-encoder affine probe has one exact 10000-update budget")
        self.final_probe_updates = updates


@dataclass
class AnomalyPolicy:
    """Retain a reason instead of checkpointing nonfinite or pathological progress."""

    clock: Callable[[], float]
    started_at: float
    heartbeat_at: float
    wall_time_limit: int
    oom_events: int = 0
    initial_losses: list[float] = field(default_factory=list)
    pathological_losses: int = 0

    def observe(self, loss: float) -> None:
        if not math.isfinite(loss):
            raise ProtocolError("One nonfinite loss aborts the registered attempt")
        if len(self.initial_losses) < 20:
            self.initial_losses.append(loss)
        else:
            from statistics import median

            pathological = loss <= 1e-8 or loss >= 10 * median(self.initial_losses)
            self.pathological_losses = self.pathological_losses + 1 if pathological else 0
            if self.pathological_losses >= 50:
                raise ProtocolError("Fifty consecutive pathological losses abort the feasibility attempt")
        self.check_time()

    def check_time(self) -> None:
        current = self.clock()
        if current - self.started_at >= self.wall_time_limit:
            raise ProtocolError("Declared wall-time ceiling exceeded")
        if current - self.heartbeat_at >= HEARTBEAT_SECONDS:
            raise ProtocolError("No persisted heartbeat for fifteen minutes")

    def record_heartbeat(self) -> None:
        self.heartbeat_at = self.clock()

    def out_of_memory(self) -> None:
        self.oom_events += 1
        if self.oom_events >= MAX_OOM:
            raise ProtocolError("Two out-of-memory events abort the registered attempt")
