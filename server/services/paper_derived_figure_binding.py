"""Strict original-input and output bindings for paper-only typography variants."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("Paper figure bindings require explicit project-local paths")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink() or path.stat().st_nlink > 1:
        raise ValueError("Paper figure input is missing, linked or outside its owned project")
    return path


def bound_original_inputs(root: Path, entry: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Verify every original source, pixel variant and scientific input before reuse."""
    metadata = entry.get("metadata") or {}
    if metadata.get("producer_kind") != "deterministic":
        raise ValueError("Paper-local typography cannot redraw a model-owned or undeclared producer")
    original = [(entry.get("source_path"), entry.get("source_sha256")),
                (entry.get("output_path"), entry.get("output_sha256"))]
    variants, hashes = metadata.get("rendered_variants") or {}, metadata.get("rendered_variant_sha256") or {}
    architecture = (metadata.get("production_strategy") == "deterministic_architecture"
                    and Path(str(entry.get("source_path") or "")).suffix.casefold() == ".json")
    expected_variants = {"json", "pdf", "svg", "png"} if architecture else {"pdf", "svg", "png"}
    python_source = (not architecture and 'py' in variants
                     and Path(str(entry.get('source_path') or '')).suffix.casefold() == '.py')
    if python_source:
        expected_variants.add('py')
    if set(variants) != expected_variants or set(hashes) != set(variants):
        raise ValueError("Paper figure projection requires all three hash-bound original variants")
    if architecture and (variants["json"] != entry.get("source_path") or hashes["json"] != entry.get("source_sha256")):
        raise ValueError("Paper FigureSpec editable source differs from its canonical JSON variant")
    if python_source and (variants['py'] != entry.get('source_path') or hashes['py'] != entry.get('source_sha256')):
        raise ValueError('Paper plot editable source differs from its canonical Python variant')
    original.extend((path, hashes.get(kind)) for kind, path in variants.items())
    scientific = metadata.get("source_data") or []
    if (not isinstance(scientific, list) or not scientific
            or any(not isinstance(path, str) or not path for path in scientific)
            or len(set(scientific)) != len(scientific)):
        raise ValueError("Paper figure projection requires explicit scientific source bindings")
    scientific_hashes = _scientific_source_hashes(metadata, scientific)
    original.extend((relative, scientific_hashes.get(relative)) for relative in scientific)
    bound, inventories = {}, []
    for relative, expected in original:
        path = local_path(root, relative)
        actual = file_sha256(path)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected) or actual != expected:
            raise ValueError(f"Paper figure original input hash is missing or stale: {relative}")
        bound[path.relative_to(root).as_posix()] = actual
        if path.suffix.casefold() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows, fields = list(reader), list(reader.fieldnames or [])
            if not rows or not fields:
                raise ValueError("Paper figure cannot project an empty scientific CSV")
            inventories.append({"path": path.relative_to(root).as_posix(), "sha256": actual,
                                "rows": len(rows), "fields": fields})
    return bound, inventories


def _scientific_source_hashes(metadata: dict, scientific: list[str]) -> dict[str, str]:
    """Consume declared historical pins, never recompute missing source attestations."""
    hashes = metadata.get("source_data_sha256")
    if hashes is not None:
        if not isinstance(hashes, dict) or set(hashes) != set(scientific):
            raise ValueError("Paper figure scientific hash inventory differs from its declared sources")
        if metadata.get("source_bindings") is None:
            return hashes
    bindings = metadata.get("source_bindings")
    if (metadata.get("production_strategy") not in {"deterministic_architecture", "deterministic_template", "deterministic_plot"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(metadata.get("producer_input_sha256") or ""))
            or not isinstance(bindings, list) or len(bindings) != len(scientific)
            or any(not isinstance(item, dict) or set(item) != {"path", "sha256"}
                   or not isinstance(item["path"], str) or not item["path"]
                   or not isinstance(item["sha256"], str) for item in bindings)):
        raise ValueError("Paper figure projection requires complete native scientific source pins")
    declared = {item["path"]: item["sha256"] for item in bindings}
    if len(declared) != len(bindings) or set(declared) != set(scientific):
        raise ValueError("Paper native source bindings are incomplete or duplicated")
    if hashes is not None and hashes != declared:
        raise ValueError("Paper native and scientific source hash declarations conflict")
    return declared


def placement_contract(value: dict[str, Any]) -> dict[str, Any]:
    """Require measured placement width, never a generic 6.5-inch substitute."""
    width = value.get("width_bp", value.get("placed_width_bp"))
    minimum, target = value.get("minimum_font_bp", 8.0), value.get("target_font_bp", 8.5)
    digest = value.get("contract_sha256")
    if (any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
            for item in (width, minimum, target)) or width <= 0 or minimum < 8.0 or target < max(8.5, minimum)
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
        raise ValueError("Paper figure requires a hash-bound actual print width and readable-font contract")
    return {**value, "width_bp": float(width), "minimum_font_bp": float(minimum), "target_font_bp": float(target)}


def verified_print_placement(root: Path, entry: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Recompute the real original manuscript placement; self-signed widths are not evidence."""
    from .publication_print_contract import read_publication_print_contract

    contract = placement_contract(value)
    main = _original_print_entrypoint(root)
    measured = read_publication_print_contract(root, main_tex=main).to_dict()
    if main.name == "ORIGINAL_MAIN.tex":
        measured = _canonical_original_contract(measured, main.relative_to(root).as_posix())
    placements = [item for item in measured["placements"] if item["graphic_relative"] == entry["output_path"]]
    if (not placements or contract.get("print_contract") != measured
            or contract["contract_sha256"] != measured["contract_sha256"]
            or not math.isclose(contract["width_bp"], min(item["width_bp"] for item in placements), abs_tol=1e-6)
            or contract["minimum_font_bp"] != measured["minimum_font_bp"]
            or contract["target_font_bp"] != measured["target_font_bp"]
            or contract.get("graphic_relative") != entry["output_path"]):
        raise ValueError("Paper figure placement differs from its actual current template and original manuscript")
    return contract


def _original_print_entrypoint(root: Path) -> Path:
    """Use the archived entrypoint only for an active exact print-overlay transaction."""
    main = local_path(root, "paper/main.tex")
    if "derived-figures/" not in main.read_text(encoding="utf-8-sig"):
        return main
    receipt = json.loads(local_path(root, "paper/derived-figures/PRINT_PROJECTION.json").read_text(encoding="utf-8-sig"))
    preserved = local_path(root, "paper/derived-figures/ORIGINAL_MAIN.tex")
    if (receipt.get("schema") != 1 or receipt.get("original_main_path") != preserved.relative_to(root).as_posix()
            or receipt.get("original_main_sha256") != file_sha256(preserved)):
        raise ValueError("Active paper print projection lacks its exact original manuscript entrypoint")
    sources = receipt.get("sources") or []
    record = next((item for item in sources if isinstance(item, dict) and item.get("original_path") == "paper/main.tex"), None)
    if not record or record.get("output_path") != "paper/main.tex" or record.get("output_sha256") != file_sha256(main):
        raise ValueError("Current print entrypoint differs from its exact graphics-only projection transaction")
    return preserved


def _canonical_original_contract(payload: dict[str, Any], archive_relative: str) -> dict[str, Any]:
    """An exact archived main has the canonical identity it possessed before projection."""
    from .publication_print_contract import PublicationPrintContract

    sources = {("paper/main.tex" if key == archive_relative else key): value
               for key, value in payload["template_source_sha256"].items()}
    placements = tuple({**item, "source_relative": "paper/main.tex" if item["source_relative"] == archive_relative
                         else item["source_relative"]} for item in payload["placements"])
    return PublicationPrintContract(payload["text_width_bp"], payload["column_width_bp"], sources, placements,
                                    payload["minimum_font_bp"], payload["target_font_bp"]).to_dict()


def pdf_print_geometry(pdf: Path, placement: dict[str, Any]) -> dict[str, Any]:
    """Measure the exported PDF, including tight-bbox expansion, at actual print scale."""
    import fitz
    from .publication_pdf_fonts import minimum_readable_font_pt
    from .figure_svg_text_geometry import rendered_svg_text_geometry

    with fitz.open(pdf) as document:
        if len(document) != 1:
            raise ValueError("A paper figure variant must be exactly one page")
        page = document[0]
        native = minimum_readable_font_pt(page)
        width, height = float(page.rect.width), float(page.rect.height)
    if native <= 0 or width <= 0:
        raise ValueError("Paper figure PDF has no verifiable readable text or page bounds")
    scaled = native * placement["width_bp"] / width
    collisions = rendered_svg_text_geometry(pdf)
    return {"native_width_bp": width, "native_height_bp": height,
            "native_minimum_font_bp": native, "placed_width_bp": placement["width_bp"],
            "placed_height_bp": height * placement["width_bp"] / width,
            "minimum_placed_font_bp": scaled, "text_geometry_findings": collisions}


def stable_json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
