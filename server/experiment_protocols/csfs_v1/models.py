"""Fixed CSFS-v1 encoders and separately fitted frozen-encoder affine probes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import torch
from torch import Tensor, nn

from .protocol import CANONICAL_CHANNELS, DROPOUT, EMBEDDING_DIM, KERNEL_SIZE, MODEL_WIDTHS, PRIVATE_DIM, SHARED_DIM, VIEW_KEYS

CSFS_METHODS = ("csfs", "channel_only", "frequency_only", "full_latent", "no_private", "shuffled_pair", "random_init")


def validated_views(batch: Mapping[str, Any]) -> dict[str, tuple[Tensor, Tensor]]:
    """Require four canonical-channel composites and explicit available masks."""
    result = {}
    size = None
    for name in VIEW_KEYS:
        signal, mask = batch.get(name), batch.get(name[0] + "_mask")
        if (not isinstance(signal, Tensor) or signal.ndim != 3 or signal.shape[1] != len(CANONICAL_CHANNELS)
                or signal.shape[0] < 1 or signal.shape[2] < 1 or not signal.is_floating_point()
                or not isinstance(mask, Tensor) or mask.dtype != torch.bool
                or mask.shape != signal.shape[:2] or mask.device != signal.device
                or (mask.sum(1) < 4).any()):
            raise ValueError("CSFS-v1 requires four [batch,19,time] tensors with explicit >=4-channel boolean masks")
        if size is not None and signal.shape != size:
            raise ValueError("CSFS-v1 composite batch and temporal shapes must match")
        size = signal.shape
        visible = torch.where(mask.unsqueeze(-1), signal, torch.zeros_like(signal))
        if not torch.isfinite(visible).all():
            raise ValueError("CSFS-v1 available channel samples must be finite")
        result[name] = (visible, mask)
    return result


class TemporalBackbone(nn.Module):
    """One shared 19-channel, kernel-15, four-block backbone; no learned imputation."""

    def __init__(self) -> None:
        super().__init__()
        modules = []
        previous = len(CANONICAL_CHANNELS)
        for width in MODEL_WIDTHS:
            modules.extend((nn.Conv1d(previous, width, KERNEL_SIZE, padding=KERNEL_SIZE // 2), nn.GELU(), nn.Dropout(DROPOUT)))
            previous = width
        self.blocks = nn.Sequential(*modules)

    def temporal(self, signal: Tensor, mask: Tensor) -> Tensor:
        if (signal.ndim != 3 or signal.shape[1] != len(CANONICAL_CHANNELS)
                or mask.shape != signal.shape[:2] or mask.dtype != torch.bool or mask.device != signal.device):
            raise ValueError("Temporal backbone requires canonical-channel signals and explicit masks")
        masked = torch.where(mask.unsqueeze(-1), signal, torch.zeros_like(signal))
        if not torch.isfinite(masked).all():
            raise ValueError("Temporal backbone cannot encode nonfinite available samples")
        return self.blocks(masked)

    def forward(self, signal: Tensor, mask: Tensor) -> Tensor:
        return self.temporal(signal, mask).mean(dim=-1)


class CSFSModel(nn.Module):
    """Encode only the four crossed views; SSL and primary inference remain separate."""

    def __init__(self, method_id: str = "csfs") -> None:
        super().__init__()
        if method_id not in CSFS_METHODS:
            raise ValueError("Unknown CSFS-v1 factorized method: " + str(method_id))
        self.method_id = method_id
        self.backbone = TemporalBackbone()
        self.representation_dim = EMBEDDING_DIM if method_id in {"no_private", "full_latent"} else SHARED_DIM
        self.shared_projector = nn.Linear(EMBEDDING_DIM, EMBEDDING_DIM if method_id == "no_private" else SHARED_DIM, bias=False)
        self.private_projector = None if method_id == "no_private" else nn.Linear(EMBEDDING_DIM, PRIVATE_DIM, bias=False)

    def encode_view(self, signal: Tensor, mask: Tensor) -> dict[str, Tensor]:
        encoded = self.backbone(signal, mask)
        result = {"backbone": encoded, "shared": self.shared_projector(encoded)}
        if self.private_projector is not None:
            result["private"] = self.private_projector(encoded)
        return result

    def forward(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        views = {name: self.encode_view(signal, mask) for name, (signal, mask) in validated_views(batch).items()}
        representation = torch.stack([
            torch.cat((views[name]["shared"], views[name]["private"]), dim=-1)
            if self.method_id == "full_latent" else views[name]["shared"] for name in VIEW_KEYS
        ]).mean(dim=0)
        return {"views": views, "shared_embedding": representation}

    def representation(self, batch: Mapping[str, Any]) -> Tensor:
        return self(batch)["shared_embedding"]

    def ssl_loss(self, batch: Mapping[str, Any], *, generator: torch.Generator | None = None) -> dict[str, Tensor]:
        from .objectives import csfs_objective

        if self.method_id == "random_init":
            raise ValueError("Random initialization is a no-SSL reference; it cannot perform pretraining updates")
        return csfs_objective(self(batch)["views"], self.method_id, generator=generator)


class FrozenLinearProbe(nn.Module):
    """A fresh affine head alone can learn; the encoder stays frozen even in train mode."""

    def __init__(self, encoder: nn.Module, num_classes: int) -> None:
        super().__init__()
        if type(num_classes) is not int or num_classes < 2:
            raise ValueError("The registered classification probe requires >=2 classes")
        self.encoder = encoder
        self.encoder.requires_grad_(False)
        self.encoder.eval()
        self.head = nn.Linear(encoder.representation_dim, num_classes)

    def train(self, mode: bool = True):
        super().train(mode)
        self.encoder.eval()
        return self

    def features(self, batch: Mapping[str, Any]) -> Tensor:
        if any(parameter.requires_grad for parameter in self.encoder.parameters()):
            raise ValueError("Primary linear-probe inference requires a frozen encoder")
        self.encoder.eval()
        with torch.no_grad():
            return self.encoder.representation(batch)

    def forward(self, batch: Mapping[str, Any]) -> Tensor:
        return self.head(self.features(batch))

    def freeze(self):
        self.requires_grad_(False)
        self.eval()
        return self
