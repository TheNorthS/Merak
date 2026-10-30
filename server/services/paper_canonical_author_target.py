"""Map exact runtime-owned section projections back to their canonical author."""

import re
from pathlib import Path


def canonical_author_target(root: Path, target: str) -> str:
    normalized = str(target).replace("\\", "/")
    match = re.fullmatch(r"paper/(?:derived-figures/tex/(?:assembly-layout/paper/)?|assembly-layout/paper/)"
        r"sections/([0-9]{2}_[A-Za-z0-9_]+\.tex)", normalized)
    if match is None:
        return target
    canonical = "paper/sections/" + match.group(1)
    path = (root / canonical).resolve()
    if path.is_relative_to(root.resolve()) and path.is_file():
        return canonical
    return target


def canonical_author_feedback(root: Path, text: str) -> str:
    """Preserve reviewer meaning while resolving known print-section pointers."""
    return re.sub(r"paper[\\/][A-Za-z0-9_.\\/-]+\.tex",
        lambda match: canonical_author_target(root, match.group()), str(text))


def runtime_presentation_target(root: Path, target: str) -> bool:
    """Unmapped print outputs belong to the renderer, never a manuscript author."""
    canonical = canonical_author_target(root, target).replace("\\", "/")
    return canonical.startswith(("paper/derived-figures/", "paper/assembly-layout/"))


def presentation_repair_metadata(root: Path, targets: list[str]) -> dict:
    """Keep renderer findings actionable without granting a model metadata writes."""
    if not any(runtime_presentation_target(root, target) for target in targets):
        return {}
    return {"owner_node": "paper", "upstream_node": "paper", "producer_kind": "deterministic",
            "category": "paper_presentation",
            "repair_capability": "paper-print-projection", "runtime_operation": "derive_paper_figure",
            "legal_write_targets": [], "remediation": "Refresh the runtime-owned print projection; "
            "preserve canonical sources and manuscript sections. Do not edit derived files with a model."}
