"""Matched CSFS-v1 contextual/masked references and the complete method registry.

The plan fixes spans and fractions but not a contextual network. This trusted
implementation declares parameter-free nearest-visible-neighbor context and one
192-to-192 linear predictor. It is a specified BENDR-style control, not the
published BENDR architecture. The predictor participates in every reference loss.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .models import CSFSModel, TemporalBackbone, validated_views
from .protocol import EMBEDDING_DIM, METHOD_IDS, TEMPERATURE, VIEW_KEYS


MASK_SPAN = 10
REFERENCE_DETAILS = {
    "mask_span": MASK_SPAN, "bendr_mask_fraction": 0.20, "prediction_mask_fraction": 0.50,
    "context": "mean of nearest visible left/right latent step, excluding masked targets",
    "predictor": "bias-free linear 192-to-192", "last_span": "truncate to exactly ceil(fraction*steps) masked positions",
    "loss_positions": "masked positions of all four clean-parent composites",
    "contrastive_negatives": "other batch parents at the same within-sample masked ordinal",
    "targets": "clean latent targets; stop-gradient only for masked-latent MSE",
}


def latent_span_mask(batch_size: int, steps: int, fraction: float, *,
                     generator: torch.Generator | None = None, device: torch.device | None = None) -> Tensor:
    """Seeded nonoverlapping contiguous spans; the last span meets the exact count."""
    if (type(batch_size) is not int or batch_size < 1 or type(steps) is not int
            or steps < 2 * MASK_SPAN or fraction not in {0.20, 0.50}):
        raise ValueError("Registered latent masking requires >=20 steps and fraction 0.20 or 0.50")
    count = math.ceil(steps * fraction)
    masks = torch.zeros(batch_size, steps, dtype=torch.bool)
    for sample in range(batch_size):
        candidates = torch.randperm(steps // MASK_SPAN, generator=generator).tolist()
        remaining = count
        for block in candidates:
            width = min(MASK_SPAN, remaining)
            start = block * MASK_SPAN
            masks[sample, start:start + width] = True
            remaining -= width
            if remaining == 0:
                break
        if remaining:
            raise ValueError("Registered latent masking cannot fit its declared spans")
    return masks.to(device=device)


def visible_temporal_context(latent: Tensor, mask: Tensor) -> Tensor:
    """Masked target values cannot enter any context prediction, even indirectly."""
    if latent.ndim != 3 or mask.shape != (latent.shape[0], latent.shape[2]) or mask.dtype != torch.bool:
        raise ValueError("Temporal context requires [batch,192,time] and a matching temporal mask")
    if mask.all(dim=1).any():
        raise ValueError("A contextual reference must retain visible latent positions")
    steps = latent.shape[-1]
    indices = torch.arange(steps, device=latent.device).expand(mask.shape)
    left = torch.cummax(torch.where(~mask, indices, -1), dim=1).values
    right = torch.flip(torch.cummin(torch.flip(torch.where(~mask, indices, steps), (1,)), dim=1).values, (1,))
    visible = latent.masked_fill(mask.unsqueeze(1), 0)
    left_values = visible.gather(2, left.clamp(min=0).unsqueeze(1).expand_as(latent)) * (left >= 0).unsqueeze(1)
    right_values = visible.gather(2, right.clamp(max=steps - 1).unsqueeze(1).expand_as(latent)) * (right < steps).unsqueeze(1)
    divisor = ((left >= 0).to(latent.dtype) + (right < steps).to(latent.dtype)).unsqueeze(1)
    return (left_values + right_values) / divisor


def temporal_context_infonce(predicted: Tensor, targets: Tensor) -> Tensor:
    """Bounded masked-position batch negatives, never an all-window quadratic matrix."""
    if (predicted.ndim != 3 or targets.shape != predicted.shape or predicted.shape[0] < 2
            or not torch.isfinite(predicted).all() or not torch.isfinite(targets).all()):
        raise ValueError("Masked contextual contrast requires >=2 batch parents at each masked ordinal")
    first, second = F.normalize(predicted, dim=-1).transpose(0, 1), F.normalize(targets, dim=-1).transpose(0, 1)
    logits = torch.bmm(first, second.transpose(1, 2)) / TEMPERATURE
    positions, batch_size = logits.shape[:2]
    labels = torch.arange(batch_size, device=logits.device).repeat(positions)
    return (F.cross_entropy(logits.reshape(-1, batch_size), labels)
            + F.cross_entropy(logits.transpose(1, 2).reshape(-1, batch_size), labels)) / 2


class MaskedTemporalReference(nn.Module):
    """Same backbone; reference predictor is updated by genuine masked-context loss."""

    def __init__(self, method_id: str) -> None:
        super().__init__()
        if method_id not in {"bendr_context", "masked_latent"}:
            raise ValueError("Unknown registered masked reference")
        self.method_id, self.representation_dim = method_id, EMBEDDING_DIM
        self.backbone, self.predictor = TemporalBackbone(), nn.Linear(EMBEDDING_DIM, EMBEDDING_DIM, bias=False)

    def representation(self, batch: Mapping[str, Any]) -> Tensor:
        return torch.stack([self.backbone(signal, mask) for signal, mask in validated_views(batch).values()]).mean(dim=0)

    def forward(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        views = {name: {"shared": self.backbone(signal, mask)}
                 for name, (signal, mask) in validated_views(batch).items()}
        return {"views": views, "shared_embedding": torch.stack([views[name]["shared"] for name in VIEW_KEYS]).mean(dim=0)}

    def ssl_loss(self, batch: Mapping[str, Any], *, generator: torch.Generator | None = None) -> dict[str, Tensor]:
        losses = []
        fraction = 0.20 if self.method_id == "bendr_context" else 0.50
        for signal, channels in validated_views(batch).values():
            latent = self.backbone.temporal(signal, channels)
            mask = latent_span_mask(latent.shape[0], latent.shape[2], fraction, generator=generator, device=latent.device)
            contextual = visible_temporal_context(latent, mask).transpose(1, 2)
            predictions = self.predictor(contextual)[mask].reshape(latent.shape[0], -1, EMBEDDING_DIM)
            target_latent = latent.detach() if self.method_id == "masked_latent" else latent
            clean_targets = target_latent.transpose(1, 2)[mask].reshape_as(predictions)
            losses.append(temporal_context_infonce(predictions, clean_targets)
                          if self.method_id == "bendr_context" else F.mse_loss(predictions, clean_targets))
        loss = torch.stack(losses).mean()
        return {"loss": loss, "masked_reference_loss": loss}


def build_method(method_id: str) -> nn.Module:
    """Only registered methods; random initialization intentionally has no SSL step."""
    if method_id not in METHOD_IDS:
        raise ValueError("Method is outside the frozen CSFS-v1 comparison family")
    return MaskedTemporalReference(method_id) if method_id in {"bendr_context", "masked_latent"} else CSFSModel(method_id)
