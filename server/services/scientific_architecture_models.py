"""Contracts returned by scientific architecture compilers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArchitectureCompilation:
    spec: dict[str, Any]
    element_mappings: list[dict[str, str]]
    profile: dict[str, Any]
