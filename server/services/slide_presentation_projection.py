"""Bind slides to current paper presentations while canonical science stays frozen.

Canonical figures must already be qualified by their original owner. This
read-only consumer validates the complete active print transform and its exact
derived pixel proof; a bad projection never falls back to the old raw graphic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RECEIPT = "paper/derived-figures/PRINT_PROJECTION.json"


def _local(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if (not relative or not path.is_relative_to(root) or not path.is_file() or path.is_symlink()
            or path.stat().st_nlink > 1):
        raise ValueError("Slide presentation source is missing, linked or foreign")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_packets(root: Path) -> tuple[dict[str, dict], str]:
    from .latex_bundle import _tex_text
    from .paper_print_projection import validate_print_projection

    receipt = root / RECEIPT
    active = "derived-figures/" in _tex_text(root / "paper/main.tex")
    if not active:
        return {}, ""
    if not receipt.exists():
        raise ValueError("Slide presentation requires the current active paper print projection")
    path = _local(root, RECEIPT)
    original = path.read_bytes()
    issues = validate_print_projection(root)
    if issues:
        raise ValueError("Slide paper presentation is not current: " + "; ".join(issues))
    if path.read_bytes() != original:
        raise ValueError("Slide paper presentation changed during its current source/pixel validation")
    payload = json.loads(original.decode("utf-8-sig"))
    packets = payload.get("packets")
    if not isinstance(packets, list) or not packets or any(not isinstance(row, dict) for row in packets):
        raise ValueError("Slide paper presentation has no complete packet inventory")
    indexed = {str(row.get("asset_id") or ""): row for row in packets}
    if not all(indexed) or len(indexed) != len(packets):
        raise ValueError("Slide paper presentation contains missing or duplicate asset identities")
    return indexed, _sha(path)


def project_slide_presentations(root: Path, qualified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain canonical entries; attach independent hash-bound current output paths."""
    from .paper_derived_figure_binding import stable_json_sha256

    root = root.resolve()
    packets, receipt_hash = _validated_packets(root)
    result = []
    for item in qualified:
        canonical = {key: value for key, value in item.items() if key != "slide_presentation"}
        identity = str((canonical.get("metadata") or {}).get("semantic_key") or canonical.get("id") or "")
        packet = packets.get(identity)
        if packet is None:
            result.append(canonical)
            continue
        if (packet.get("original_path") != canonical.get("output_path")
                or packet.get("original_entry_sha256") != stable_json_sha256(canonical)):
            raise ValueError("Slide presentation differs from its qualified canonical figure owner")
        relative = str(packet.get("output_path") or "")
        output = _local(root, relative)
        variants = packet.get("derived_paths") or {}
        hashes = packet.get("derived_sha256") or {}
        if relative != variants.get("pdf") or _sha(output) != hashes.get("pdf"):
            raise ValueError("Slide presentation output differs from its verified PDF variant")
        provenance = _local(root, str(packet.get("provenance_path") or ""))
        binding = {"schema": 1, "canonical_asset_id": identity, "canonical_output_path": canonical["output_path"],
            "canonical_output_sha256": canonical["output_sha256"], "output_path": relative,
            "output_sha256": hashes["pdf"], "receipt_path": RECEIPT, "receipt_sha256": receipt_hash,
            "provenance_path": provenance.relative_to(root).as_posix(), "provenance_sha256": _sha(provenance),
            "source_paths": list(dict.fromkeys([RECEIPT, provenance.relative_to(root).as_posix(), *variants.values()])),
            "workflow_acceptance_granted": False}
        result.append({**canonical, "slide_presentation": binding})
    return result


def presentation_output_path(item: dict[str, Any]) -> str:
    """Use only the independent presentation binding attached by the qualified reader."""
    return str((item.get("slide_presentation") or {}).get("output_path") or item.get("output_path") or "")


def slide_figure_inventory(root: Path) -> str:
    """Give model and native slide producers the same canonical IDs and actual paths."""
    from .slide_figures import deck_figures

    assets = json.loads((root / "figures/SCIENTIFIC_ASSET_PLAN.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((root / "figures/FIGURE_MANIFEST.json").read_text(encoding="utf-8-sig"))
    standard, synthetic = deck_figures(root, assets, manifest)
    return "\n".join(f"- {str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or '')}: "
                     + "../" + presentation_output_path(item) for item in [*standard, *synthetic])
