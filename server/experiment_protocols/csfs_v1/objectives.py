"""Registered pair families and shared/private covariance; never supervised SSL."""

from __future__ import annotations

from collections.abc import Mapping

import torch
from torch import Tensor
from torch.nn import functional as F

from .models import VIEW_KEYS
from .protocol import PRIVATE_WEIGHT, TEMPERATURE


PAIR_FAMILIES = {
    "channel_loss": (("a_low", "b_low"), ("a_high", "b_high")),
    "spectral_loss": (("a_low", "a_high"), ("b_low", "b_high")),
    "cross_loss": (("a_low", "b_high"), ("a_high", "b_low")),
}


def symmetric_infonce(first: Tensor, second: Tensor, temperature: float = TEMPERATURE) -> Tensor:
    """Same-index positives, every other paired example negative, both directions."""
    if (first.ndim != 2 or second.shape != first.shape or first.shape[0] < 2
            or temperature != TEMPERATURE or not torch.isfinite(first).all() or not torch.isfinite(second).all()):
        raise ValueError("CSFS-v1 InfoNCE requires finite paired >=2-example matrices at temperature 0.20")
    first, second = F.normalize(first, dim=-1), F.normalize(second, dim=-1)
    logits = first @ second.T / temperature
    targets = torch.arange(first.shape[0], device=first.device)
    return (F.cross_entropy(logits, targets) + F.cross_entropy(logits.T, targets)) / 2


def shared_private_covariance(shared: Tensor, private: Tensor) -> Tensor:
    """Mean square of centered shared/private sample cross-covariance, not correlation."""
    if (shared.ndim != 2 or private.ndim != 2 or shared.shape[0] != private.shape[0]
            or shared.shape[0] < 2 or not torch.isfinite(shared).all() or not torch.isfinite(private).all()):
        raise ValueError("Cross-covariance requires paired >=2-example shared/private factors")
    centered_shared = shared - shared.mean(dim=0)
    centered_private = private - private.mean(dim=0)
    covariance = centered_shared.T @ centered_private / (shared.shape[0] - 1)
    return covariance.square().mean()


def shuffled_b_correspondence(views: Mapping[str, Mapping[str, Tensor]], *,
                              generator: torch.Generator | None = None) -> dict[str, dict[str, Tensor]]:
    """One nonidentity B-side correspondence; A and intra-B pairs are unchanged."""
    size = views["a_low"]["shared"].shape[0]
    if size < 2:
        raise ValueError("A shuffled-pair control requires >=2 parents")
    # A seeded cyclic derangement has no accidentally retained positive parents.
    shift = int(torch.randint(1, size, (), generator=generator).item())
    indices = torch.roll(torch.arange(size, device=views["a_low"]["shared"].device), shifts=shift)
    return {name: {key: value[indices] if name.startswith("b_") else value
                   for key, value in encoded.items()} for name, encoded in views.items()}


def csfs_objective(views: Mapping[str, Mapping[str, Tensor]], method_id: str = "csfs", *,
                   generator: torch.Generator | None = None) -> dict[str, Tensor]:
    if set(views) != set(VIEW_KEYS) or method_id not in {
        "csfs", "channel_only", "frequency_only", "full_latent", "no_private", "shuffled_pair"
    }:
        raise ValueError("Registered CSFS objective requires exactly its four composites and known method")
    paired = shuffled_b_correspondence(views, generator=generator) if method_id == "shuffled_pair" else views
    aligned = {name: torch.cat((item["shared"], item["private"]), dim=-1)
               if method_id == "full_latent" else item["shared"] for name, item in paired.items()}
    zero = views["a_low"]["shared"].new_zeros(())
    terms = {}
    for family, pairs in PAIR_FAMILIES.items():
        disabled = method_id == "channel_only" and family != "channel_loss" or method_id == "frequency_only" and family != "spectral_loss"
        terms[family] = zero if disabled else torch.stack([
            symmetric_infonce(aligned[first], aligned[second]) for first, second in pairs
        ]).mean()
    terms["private_loss"] = zero if method_id in {"full_latent", "no_private"} else torch.stack([
        shared_private_covariance(views[name]["shared"], views[name]["private"]) for name in VIEW_KEYS
    ]).mean()
    terms["loss"] = terms["channel_loss"] + terms["spectral_loss"] + terms["cross_loss"] + PRIVATE_WEIGHT * terms["private_loss"]
    return terms
