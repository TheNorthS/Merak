"""CPU checkpoint/OOM state for real execution; no optimizer or data invocation."""

import copy
import random
import time

import numpy as np

from .checkpoint_contract import build_resume_checkpoint
from .protocol import PRETRAIN_WINDOWS


def host_state(value):
    if isinstance(value, dict):
        return {key: host_state(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(host_state(item) for item in value)
    if isinstance(value, list):
        return [host_state(item) for item in value]
    return value.detach().cpu().clone() if hasattr(value, "detach") else copy.deepcopy(value)


def rng_state(generator, device):
    import torch

    numpy = np.random.get_state()
    return {"python": random.getstate(), "numpy": (numpy[0], numpy[1].tolist(), *numpy[2:]),
            "torch": torch.get_rng_state().clone(), "objective": generator.get_state().clone(),
            "cuda": [value.cpu().clone() for value in torch.cuda.get_rng_state_all()] if device == "cuda" else []}


def restore_rng(values, generator, device):
    import torch

    random.setstate(values["python"])
    numpy = values["numpy"]
    np.random.set_state((numpy[0], np.asarray(numpy[1], dtype=np.uint32), *numpy[2:]))
    torch.set_rng_state(values["torch"])
    generator.set_state(values["objective"])
    if device == "cuda":
        torch.cuda.set_rng_state_all(values["cuda"])


def anomaly_record(anomaly):
    return {"oom_events": anomaly.oom_events, "initial_losses": list(anomaly.initial_losses),
            "pathological_losses": anomaly.pathological_losses,
            "heartbeat_age_seconds": anomaly.clock() - anomaly.heartbeat_at}


def step_snapshot(model, optimizer, generator, policy, anomaly, cursor, seed, device, best_state=None):
    return {"model": host_state(model.state_dict()), "optimizer": host_state(optimizer.state_dict()),
            "gradients": {name: host_state(parameter.grad) for name, parameter in model.named_parameters()},
            "best_model": host_state(best_state),
            "rng": rng_state(generator, device),
            "sampler": {"seed": seed, "cursor": cursor, "window_budget": PRETRAIN_WINDOWS, "sampling_role": "pretrain"},
            "budget": {"cursor": cursor}, "policy": copy.deepcopy(policy.__dict__), "anomaly": anomaly_record(anomaly)}


def restore_step(value, model, optimizer, generator, policy, anomaly, device):
    model.load_state_dict(value["model"])
    optimizer.load_state_dict(value["optimizer"])
    for name, parameter in model.named_parameters():
        gradient = value["gradients"][name]
        parameter.grad = gradient.to(parameter.device) if gradient is not None else None
    restore_rng(value["rng"], generator, device)
    policy.__dict__.update(copy.deepcopy(value["policy"]))
    anomaly.initial_losses = list(value["anomaly"]["initial_losses"])
    anomaly.pathological_losses = value["anomaly"]["pathological_losses"]


def save_resume(writer, identity, model, optimizer, generator, policy, anomaly, best_state):
    snapshot = step_snapshot(model, optimizer, generator, policy, anomaly, policy.windows, identity.seed,
                             identity.resources.device)
    payload = build_resume_checkpoint(identity, windows=policy.windows, model=snapshot["model"],
        optimizer=snapshot["optimizer"], best_model=host_state(best_state), policy=snapshot["policy"],
        rng=snapshot["rng"], sampler=snapshot["sampler"], anomaly=snapshot["anomaly"],
        resources_elapsed_seconds=anomaly.clock() - anomaly.started_at, saved_at_unix=time.time())
    digest = writer.checkpoint("resume.pt", payload)
    writer.json("resume_binding.json", {"checkpoint_sha256": digest, "identity": payload["identity"],
                                       "windows": payload["windows"], "path": "resume.pt"})
