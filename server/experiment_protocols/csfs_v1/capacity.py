"""Actual trainable parameter matching; gradients are not optimizer-update evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import torch
from torch import nn

from .protocol import METHOD_IDS


def parameter_counts(model: nn.Module) -> dict[str, int]:
    return {"raw_parameters": sum(parameter.numel() for parameter in model.parameters()),
            "trainable_pretraining_parameters": sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)}


def gradient_participation(model: nn.Module) -> dict[str, Any]:
    """Detect unconnected/ghost trainable tensors without executing an optimizer."""
    required = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
    missing = [name for name, parameter in required.items() if parameter.grad is None]
    nonfinite = [name for name, parameter in required.items()
                 if parameter.grad is not None and not torch.isfinite(parameter.grad).all()]
    inactive = [name for name, parameter in required.items()
                if parameter.grad is not None and not torch.count_nonzero(parameter.grad)]
    return {"gradient_flow_checked": True, "missing_gradients": missing, "nonfinite_gradients": nonfinite,
            "zero_gradient_tensors": inactive, "passed": not (missing or nonfinite or inactive),
            "optimizer_updates_verified": False}


def capacity_ledger(models: Mapping[str, nn.Module], *, require_gradients: bool = False) -> dict[str, Any]:
    """All nine declared methods and <=1% actual SSL-capacity difference are required."""
    if set(models) != set(METHOD_IDS) or any(getattr(model, "method_id", None) != key for key, model in models.items()):
        raise ValueError("Capacity matching requires the exact registered method family and real method identities")
    reference = parameter_counts(models["csfs"])["trainable_pretraining_parameters"]
    if reference <= 0:
        raise ValueError("The reference encoder has no trainable pretraining capacity")
    rows = {}
    for method_id, model in models.items():
        counts = parameter_counts(model)
        deviation = abs(counts["trainable_pretraining_parameters"] - reference) / reference
        if method_id != "random_init" and deviation > 0.01:
            raise ValueError("Registered SSL capacity differs by more than 1%: " + method_id)
        gradients = gradient_participation(model) if require_gradients and method_id != "random_init" else None
        if gradients is not None and not gradients["passed"]:
            raise ValueError("Registered pretraining loss has unupdated or invalid parameter gradients: " + method_id)
        rows[method_id] = {**counts, "relative_difference": deviation, "ssl_enabled": method_id != "random_init",
                           "gradient_evidence": gradients, "optimizer_updates_verified": False}
    return {"schema": 1, "reference": "csfs", "maximum_relative_difference": 0.01, "methods": rows,
            "capacity_matched": True, "execution_performed": False, "optimizer_updates_verified": False}
