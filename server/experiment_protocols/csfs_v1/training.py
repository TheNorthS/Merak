"""Registered SSL and frozen-affine-probe routines, only called by consented study.

Unit verification uses injected policy callbacks and never executes this optimizer
on research materials. Selection freezes a checkpoint COPY, not the live encoder.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import time
from typing import Any, Callable, Sequence

from .data import BalancedSourceSampler, make_batch
from .execution_io import AttemptWriter
from .protocol import (BATCH_SIZE, CHECKPOINT_WINDOWS, FINAL_PROBE_UPDATES, GRAD_NORM_LIMIT,
                       LEARNING_RATE, PRETRAIN_WINDOWS, SELECTION_PROBE_UPDATES, WEIGHT_DECAY,
                       ExecutionResources, ProtocolError)
from .training_policy import AnomalyPolicy, SelectionPolicy, window_batches


def device_batch(batch: dict, device) -> dict:
    """Only tensor values move; parent, split and normalization metadata stay bound."""
    return {key: value.to(device) if hasattr(value, "to") else value for key, value in batch.items()}


def fixed_batches(segments: Sequence[Any], run_seed: int, device):
    if not segments:
        raise ProtocolError("A frozen evaluation partition cannot be empty")
    for index in range(0, len(segments), BATCH_SIZE):
        yield device_batch(make_batch(segments[index:index + BATCH_SIZE], run_seed), device)


def memory_guard(resources: ExecutionResources) -> None:
    import psutil

    used = psutil.Process().memory_info().rss
    if resources.device == "cuda":
        import torch

        used = max(used, torch.cuda.memory_allocated())
    if used > resources.peak_memory_bytes:
        raise ProtocolError("Declared peak-memory ceiling exceeded")


def seed_runtime(seed: int, device: str) -> None:
    import random
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device == "cuda":
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)


def _finite_update(loss, parameters, optimizer) -> None:
    import torch

    if loss.ndim != 0 or not torch.isfinite(loss):
        raise ProtocolError("One nonfinite scalar loss aborts the attempt")
    loss.backward()
    if any(parameter.grad is None or not torch.isfinite(parameter.grad).all() for parameter in parameters):
        raise ProtocolError("Missing optimizer participation or one nonfinite gradient aborts the attempt")
    norm = torch.nn.utils.clip_grad_norm_(parameters, GRAD_NORM_LIMIT, error_if_nonfinite=True)
    if not torch.isfinite(norm):
        raise ProtocolError("One nonfinite gradient norm aborts the attempt")
    optimizer.step()
    if any(not torch.isfinite(parameter).all() for parameter in parameters):
        raise ProtocolError("An optimizer update produced nonfinite parameters")


def train_frozen_probe(model, corpus, fold, segments: Sequence[Any], *, seed: int,
                       updates: int, resources: ExecutionResources, anomaly: AnomalyPolicy,
                       writer: AttemptWriter):
    """Exactly the registered fresh selection/final updates, source labels only."""
    import torch
    from .models import FrozenLinearProbe

    if updates not in {SELECTION_PROBE_UPDATES, FINAL_PROBE_UPDATES}:
        raise ProtocolError("No additional affine-probe tuning budget is allowed")
    seed_runtime(seed, resources.device)
    encoder = copy.deepcopy(model).to(resources.device)
    probe = FrozenLinearProbe(encoder, len(corpus.label_vocabulary)).to(resources.device)
    optimizer = torch.optim.AdamW(probe.head.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    sampler = BalancedSourceSampler(corpus, fold, segments, seed, window_budget=updates * BATCH_SIZE,
                                   sampling_role="probe")
    stream = iter(sampler)
    for index in range(updates):
        anomaly.check_time()
        batch = device_batch(make_batch([next(stream) for _ in range(BATCH_SIZE)], seed), resources.device)
        _safe_update(probe, optimizer, lambda: torch.nn.functional.cross_entropy(probe(batch), batch["labels"]),
                     list(probe.head.parameters()), torch.Generator().manual_seed(seed + index),
                     SelectionPolicy(), anomaly, index, seed, resources)
        memory_guard(resources)
        if index % 10 == 0:
            writer.json("heartbeat.json", {"probe_updates": index + 1, "updated_at": time.time()})
            anomaly.record_heartbeat()
    probe.freeze()
    return probe


@dataclass(frozen=True)
class TrainedCondition:
    model: Any
    probe: Any
    checkpoint_sha256: str
    probe_sha256: str
    selection_score: float
    budget: dict
    anomaly: AnomalyPolicy


def train_condition(model, corpus, fold, prepared, *, seed: int, resources: ExecutionResources,
                    writer: AttemptWriter, evaluate_selection: Callable, resume_request: dict | None = None) -> TrainedCondition:
    """Target data never enters SSL, probes, early stopping, or checkpoint choice."""
    import torch

    seed_runtime(seed, resources.device)
    model.to(resources.device)
    now = time.monotonic()
    anomaly = AnomalyPolicy(time.monotonic, now, now, resources.wall_time_seconds)
    policy, best_state = SelectionPolicy(), None
    if model.method_id == "random_init":
        if resume_request:
            raise ProtocolError("A random-init reference has no SSL checkpoint to resume")
        best_state = copy.deepcopy(model.state_dict())
        selection = _selection(model, corpus, fold, prepared, seed, 0, resources, writer, anomaly, evaluate_selection)
        policy.best_score = selection
        policy.evaluations, policy.selection_updates = 1, SELECTION_PROBE_UPDATES
    else:
        best_state = _pretrain(model, corpus, fold, prepared, seed, resources, writer, anomaly, policy,
                               evaluate_selection, resume_request)
    model.load_state_dict(best_state)
    checkpoint = writer.checkpoint("selected_encoder.pt", model.state_dict())
    probe = train_frozen_probe(model, corpus, fold, prepared.training, seed=seed,
                               updates=FINAL_PROBE_UPDATES, resources=resources, anomaly=anomaly, writer=writer)
    policy.complete_probe(FINAL_PROBE_UPDATES)
    probe_hash = writer.checkpoint("final_probe.pt", probe.state_dict())
    budget = {"ssl_windows": policy.windows, "selection_evaluations": policy.evaluations,
              "selection_probe_updates": policy.selection_updates,
              "final_probe_updates": policy.final_probe_updates, "checkpoint_history": policy.events,
              "early_stopped": policy.windows < PRETRAIN_WINDOWS and model.method_id != "random_init",
              "encoder_frozen_during_probes": True, "target_fitting": False}
    writer.json("budget.json", budget)
    return TrainedCondition(model, probe, checkpoint, probe_hash, policy.best_score, budget, anomaly)


def _selection(model, corpus, fold, prepared, seed, checkpoint, resources, writer, anomaly, evaluate):
    probe = train_frozen_probe(model, corpus, fold, prepared.training, seed=seed + checkpoint,
                               updates=SELECTION_PROBE_UPDATES, resources=resources, anomaly=anomaly, writer=writer)
    encoder_hash = writer.checkpoint("selection_encoder.pt", model.state_dict())
    probe_hash = writer.checkpoint("selection_probe.pt", probe.state_dict())
    score = evaluate(probe, encoder_hash, probe_hash)
    writer.json(f"selection-{checkpoint}.json", {"score": score, "checkpoint": checkpoint,
                "encoder_sha256": encoder_hash, "probe_sha256": probe_hash,
                "probe_updates": SELECTION_PROBE_UPDATES, "fit_partition": "source_training_only"})
    anomaly.record_heartbeat()
    return score


def _pretrain(model, corpus, fold, prepared, seed, resources, writer, anomaly, policy, evaluate, resume_request):
    import torch

    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    sampler = BalancedSourceSampler(corpus, fold, prepared.training, seed)
    generator = torch.Generator().manual_seed(seed)
    identity = _checkpoint_identity(model, corpus, fold, prepared, seed, resources, writer)
    consumed, best_state, stream = _restore_checkpoint(resume_request, identity, model, optimizer,
                                                     generator, policy, anomaly, sampler)
    if policy.without_improvement >= 10 or consumed == PRETRAIN_WINDOWS:
        return best_state
    for segments in window_batches(stream, consumed_windows=consumed):
        model.train()
        batch = device_batch(make_batch(segments, seed), resources.device)
        _safe_update(model, optimizer, lambda: model.ssl_loss(batch, generator=generator)["loss"],
                     parameters, generator, policy, anomaly, consumed, seed, resources, ssl=True,
                     best_state=best_state)
        memory_guard(resources)
        consumed += len(segments)
        writer.json("heartbeat.json", {"ssl_windows": consumed, "updated_at": time.time()})
        anomaly.record_heartbeat()
        if consumed % CHECKPOINT_WINDOWS == 0:
            score = _selection(model, corpus, fold, prepared, seed, consumed // CHECKPOINT_WINDOWS,
                               resources, writer, anomaly, evaluate)
            previous = policy.best_checkpoint
            stop = policy.observe(consumed, score, SELECTION_PROBE_UPDATES)
            if policy.best_checkpoint != previous:
                best_state = copy.deepcopy(model.state_dict())
                writer.checkpoint("best_encoder.pt", best_state)
            from .training_state import save_resume

            save_resume(writer, identity, model, optimizer, generator, policy, anomaly, best_state)
            if stop:
                break
    if best_state is None:
        raise ProtocolError("No complete source-validation-selected checkpoint was produced")
    return best_state


def _safe_update(model, optimizer, loss_factory, parameters, generator, policy, anomaly, cursor, seed, resources,
                 *, ssl=False, best_state=None):
    import torch
    from .execution_safety import retry_oom_step
    from .training_state import step_snapshot, restore_step

    def operation():
        optimizer.zero_grad(set_to_none=True)
        loss = loss_factory()
        if ssl:
            anomaly.observe(float(loss.detach().cpu()))
        _finite_update(loss, parameters, optimizer)

    retry_oom_step(operation,
        lambda: step_snapshot(model, optimizer, generator, policy, anomaly, cursor, seed, resources.device, best_state),
        lambda state: restore_step(state, model, optimizer, generator, policy, anomaly, resources.device),
        anomaly, torch.cuda.empty_cache if resources.device == "cuda" else lambda: None,
        oom_exception=torch.cuda.OutOfMemoryError)


def _checkpoint_identity(model, corpus, fold, prepared, seed, resources, writer):
    from .checkpoint_contract import CheckpointIdentity

    return CheckpointIdentity(writer.identity["config_sha256"], writer.identity["source_sha256"],
        corpus.sha256, fold.sha256, prepared.normalizer.sha256, seed, model.method_id,
        writer.identity["target_id"], writer.identity["fit_role"], resources)


def _restore_checkpoint(request, identity, model, optimizer, generator, policy, anomaly, sampler):
    from .checkpoint_contract import load_bound_checkpoint, resumed_resource_origin, resume_seeded_stream
    from .training_state import restore_rng

    if request is None:
        return 0, None, iter(sampler)
    payload = load_bound_checkpoint(request["path"], request["sha256"], identity,
                                    owned_attempt_root=request["attempt_root"])
    anomaly.started_at, anomaly.heartbeat_at = resumed_resource_origin(anomaly.clock, payload)
    anomaly.oom_events = payload["anomaly"]["oom_events"]
    anomaly.initial_losses = list(payload["anomaly"]["initial_losses"])
    anomaly.pathological_losses = payload["anomaly"]["pathological_losses"]
    anomaly.check_time()
    model.load_state_dict(payload["model"])
    optimizer.load_state_dict(payload["optimizer"])
    policy.__dict__.update(payload["policy"])
    restore_rng(payload["rng"], generator, identity.resources.device)
    return payload["windows"], payload["best_model"], resume_seeded_stream(lambda: sampler, payload["windows"])
