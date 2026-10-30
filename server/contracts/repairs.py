"""Capability-based repair ownership for structured workflow findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RepairCapability:
    identity: str
    owner: str
    validator: str
    target_prefixes: tuple[str, ...]
    message_markers: tuple[str, ...] = ()


repair_capability_registry = (
    RepairCapability("slide-source", "ppt", "slide-source-v1", ("slides/",)),
    RepairCapability(
        "paper-print-projection", "paper", "paper-print-contract-v1",
        ("paper/derived-figures/", "paper/assembly-layout/"), ("paper typography projection",),
    ),
    RepairCapability(
        "python-entrypoint-contract", "exp-design", "python-entrypoint-v1",
        (
            "experiments/implementation_blueprint.json",
            "experiments/run_spec.json",
            "experiments/src/",
        ),
        ("entrypoint", "execution entry"),
    ),
    RepairCapability(
        "implementation-evidence-contract", "exp-design", "method-contract-v2",
        ("experiments/method_contract.json", "experiments/src/"),
        ("implementation check", "implementation evidence", "reachable"),
    ),
    RepairCapability(
        "figure-source-mapping", "exp-design", "figure-source-mapping-v1",
        ("experiments/src/", "experiments/method_contract.json"),
        (
            "element mapping", "source mapping", "component mapping",
            "declared implementation components",
        ),
    ),
    RepairCapability(
        "figure-layout", "figure", "figure-print-contract-v1",
        ("figures/",),
        ("font", "overlap", "clipping", "primary visual groups", "layout"),
    ),
    RepairCapability(
        "result-provenance", "results", "result-analysis-build-v1",
        ("experiments/results/",),
        ("provenance", "run identity", "metric"),
    ),
    RepairCapability(
        "manuscript-source", "paper", "paper-source-v1",
        ("paper/",),
        ("latex", "section", "manuscript"),
    ),
)


def repair_capability_for(
    *, message: str, target_files: Iterable[str], category: str = "",
    owner_node: str = "",
) -> RepairCapability | None:
    """Match a repair capability within the artifact's established ownership.

    Broad diagnostic words such as ``overlap`` cannot identify a visual defect
    without a figure target, figure category, or figure-specific message.
    """
    normalized_message = f"{category} {message}".casefold()
    targets = [str(value).replace("\\", "/").casefold() for value in target_files]
    scored: list[tuple[int, RepairCapability]] = []
    for capability in repair_capability_registry:
        if owner_node and capability.owner != owner_node:
            continue
        path_hit = any(
            target.startswith(prefix) or prefix in target
            for target in targets for prefix in capability.target_prefixes
        )
        marker_hit = any(
            marker in normalized_message for marker in capability.message_markers
        )
        if capability.identity == "paper-print-projection" and not (
            path_hit and (category == "paper_presentation" or (marker_hit and category == "visual_layout"))
        ):
            continue
        if marker_hit and not path_hit:
            marker_hit = _message_scope_matches(
                capability, normalized_message, category, targets, owner_node,
            )
        score = int(path_hit) * 2 + int(marker_hit)
        if score:
            scored.append((score, capability))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _message_scope_matches(
    capability: RepairCapability, message: str, category: str,
    targets: list[str], owner_node: str,
) -> bool:
    if owner_node == capability.owner:
        return True
    if targets:
        return False
    if capability.identity != "figure-layout":
        return True
    scope = category.casefold()
    if scope.startswith("figure"):
        return True
    if scope not in {"", "quality", "risk", "peer_review", "visual_layout"}:
        return False
    return any(
        marker in message for marker in (
            "svg", "figure", "diagram", "glyph", "canvas", "图中文字", "图形布局",
        )
    )
