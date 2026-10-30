"""Produce bounded source-bound paper presentations without changing research assets.

The producer executes only exact current trusted plotting templates in-process,
or locally converts a safe deterministic SVG. Declared metric axes and population
grouping can be corrected in paper-only variants; scientific rows, intervals,
method/dataset identities and original artifacts remain immutable. A two-attempt
transaction commits only verified PDF/SVG/PNG variants and runtime provenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock
from ..utils.runtime_source_root import server_source_root
from .paper_derived_figure_binding import (bound_original_inputs, file_sha256, local_path,
                                         pdf_print_geometry, placement_contract, stable_json_sha256, verified_print_placement)
from .paper_derived_svg_projection import canonical_svg_identity, scaled_svg_typography
from .paper_trusted_plot_source import match_trusted_plot, projected_plot_source


_RENDER_LOCK = threading.Lock()
_MODULES = ("paper_derived_figure_rendering.py", "paper_derived_figure_binding.py",
            "paper_native_plot_source.py", "scientific_plot_template.py", "scientific_plotting.py",
            "paper_figurespec_source.py", "paper_figurespec_typography.py",
            "paper_derived_svg_projection.py", "paper_evaluation_svg_layout.py", "paper_trusted_plot_source.py",
            "paper_plot_semantics_projection.py", "publication_labels.py", "paper_curve_layout.py", "paper_risk_layout.py", "simulation_plot_layout.py",
            "svg_variant_conversion.py", "figure_svg_text_geometry.py", "publication_pdf_fonts.py",
            "publication_print_contract.py", "paper_derived_pixel_binding.py", "paper_matplotlib_memory.py",
            "paper_pixel_validation_cache.py")


class PaperFigureProjectionError(ValueError):
    """A typed blocking producer failure; never a mandate to alter scientific data."""

    def __init__(self, asset_id: str, issue: str, render_attempts: list | None = None):
        self.asset_id, self.issue = asset_id, issue
        self.render_attempts = list(render_attempts or [])
        super().__init__(f"Paper typography projection for {asset_id} failed: {issue}")


async def derive_paper_figure(root: Path, entry: dict[str, Any], placement: dict[str, Any]) -> dict[str, Any]:
    """Render one authorized same-source presentation variant; cancellation joins its worker."""
    root = root.resolve(strict=True)
    task = asyncio.create_task(asyncio.to_thread(_derive_transaction, root, entry, placement))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


def _renderer_digest(template: bytes = b"") -> str:
    digest = hashlib.sha256(template)
    root = server_source_root() / "services"
    for name in _MODULES:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _entry_contract(root: Path, entry: dict[str, Any], placement: dict[str, Any]) -> tuple[str, dict, dict, list]:
    identity = str((entry.get("metadata") or {}).get("semantic_key") or entry.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity):
        raise ValueError("Paper figure requires one stable canonical asset identifier")
    if _current_entry(root, identity) != entry:
        raise ValueError("Paper figure source differs from its current canonical manifest entry")
    bound, inventories = bound_original_inputs(root, entry)
    contract = verified_print_placement(root, entry, placement)
    if contract.get("graphic_relative") and local_path(root, contract["graphic_relative"]) != local_path(root, entry["output_path"]):
        raise ValueError("Paper typography placement belongs to a different canonical graphic")
    source = local_path(root, entry["source_path"])
    if source.suffix.casefold() == ".json":
        from .paper_figurespec_source import figurespec_svg_source

        figurespec_svg_source(root, entry)
    if source.suffix.casefold() == ".py":
        _name, parameters, _template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))
        data = local_path(root, parameters["data_path"])
        if data.relative_to(root).as_posix() not in {item["path"] for item in inventories}:
            raise ValueError("Trusted paper plot source reads data outside its declared scientific CSV bindings")
    return identity, contract, bound, inventories


def _derive_transaction(root: Path, entry: dict[str, Any], placement: dict[str, Any]) -> dict[str, Any]:
    identity, placement, original_inputs, inventories = _entry_contract(root, entry, placement)
    destination = (root / "paper/derived-figures" / identity).resolve()
    if not destination.is_relative_to(root / "paper/derived-figures") or destination.is_symlink():
        raise ValueError("Paper typography destination escapes its derived-artifact owner")
    destination.mkdir(parents=True, exist_ok=True)
    source = local_path(root, entry["source_path"])
    signature = _current_input_signature(root, entry, placement, original_inputs, source)
    reused = _cached_packet(root, destination, signature)
    if reused is not None:
        return reused
    original_pdf = local_path(root, entry["output_path"])
    original_geometry = pdf_print_geometry(original_pdf, placement)
    multiplier = max(1.0, placement["target_font_bp"] / original_geometry["minimum_placed_font_bp"] * 1.03)
    if source.suffix.casefold() == ".py":
        name, parameters, _template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))
        if name in {"robustness", "risk_coverage"}:
            fonts = [float(value) for key, value in parameters.items() if key.endswith("font_size")]
            multiplier = max(1.0, placement["target_font_bp"] * float(parameters["width"]) * 72
                             / placement["width_bp"] / min(fonts) * 1.03)
    candidate = None
    _prepare_matplotlib_cache(source)
    with _RENDER_LOCK, path_lock(destination / "PROVENANCE.json"):
        with tempfile.TemporaryDirectory(prefix=".candidate-", dir=destination) as directory:
            stage = Path(directory)
            rounds = []
            for attempt in range(1, 3):
                if multiplier > 4.0:
                    raise PaperFigureProjectionError(identity, "readability needs a wider or partitioned source-bound layout")
                candidate, template = _render_candidate(root, source, stage, multiplier, entry)
                _assert_original(root, original_inputs)
                geometry = pdf_print_geometry(candidate["pdf"], placement)
                rounds.append({"attempt": attempt, "font_multiplier": multiplier, **geometry})
                if geometry["minimum_placed_font_bp"] >= placement["target_font_bp"] and not geometry["text_geometry_findings"]:
                    if source.suffix.casefold() == ".py":
                        saved, _name, _template = projected_plot_source(
                            source.read_text(encoding="utf-8-sig"), root, destination / "figure", multiplier,
                        )
                        atomic_write_bytes(candidate["source"], saved.encode("utf-8"))
                    packet = _packet(root, entry, placement, original_inputs, inventories, rounds, candidate, destination, template)
                    _commit_packet(root, packet, candidate, destination)
                    return packet
                multiplier *= max(1.06, placement["target_font_bp"] / geometry["minimum_placed_font_bp"] * 1.03)
            issue = "two bounded typography attempts failed final font or collision checks"
            atomic_write_json(destination / "FAILED_PROJECTION.json", {
                "schema": 1, "input_signature": signature, "asset_id": identity,
                "issue": issue, "render_attempts": rounds, "scientific_data_changed": False,
            })
            raise PaperFigureProjectionError(identity, issue, rounds)


def _current_input_signature(root: Path, entry: dict, placement: dict, inputs: dict, source: Path) -> str:
    template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))[2] if source.suffix == ".py" else source.read_bytes()
    return stable_json_sha256({"original_entry_sha256": stable_json_sha256(entry),
                              "original_inputs_sha256": inputs, "print_placement": placement,
                              "renderer_sha256": _renderer_digest(template)})


def _cached_packet(root: Path, destination: Path, signature: str) -> dict | None:
    success = destination / "PROVENANCE.json"
    if success.is_file():
        try:
            packet = json.loads(success.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Paper derived-figure provenance is corrupt") from error
        if packet.get("input_signature") == signature and not validate_derived_figure(root, packet):
            return packet
    failure = destination / "FAILED_PROJECTION.json"
    if failure.is_file():
        try:
            record = json.loads(failure.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Paper typography failure receipt is corrupt") from error
        if record.get("schema") == 1 and record.get("input_signature") == signature:
            raise PaperFigureProjectionError(destination.name, str(record.get("issue") or "unchanged bounded failure"),
                                             record.get("render_attempts") or [])
    return None


def _render_candidate(root: Path, source: Path, stage: Path, multiplier: float,
                      entry: dict | None = None) -> tuple[dict[str, Path], bytes]:
    suffix = source.suffix.casefold()
    paths = {kind: stage / f"figure.{kind}" for kind in ("pdf", "svg", "png")}
    if suffix == ".py":
        original = source.read_text(encoding="utf-8-sig")
        _name, parameters, _template = match_trusted_plot(original)
        local_path(root, parameters["data_path"])
        code, _name, template = projected_plot_source(original, root, stage / "figure", multiplier)
        paths["source"] = stage / "figure.py"
        atomic_write_bytes(paths["source"], code.encode("utf-8"))
        _execute_trusted_plot(code, paths["source"])
    elif suffix in {".svg", ".json"}:
        from .svg_variant_conversion import convert_svg_variants
        template = source.read_bytes()
        paths["source"] = paths["svg"]
        if suffix == ".json":
            from .paper_figurespec_source import projected_figurespec_svg

            projected = projected_figurespec_svg(root, entry or {}, multiplier)
        else:
            projected = _projected_svg(template, multiplier)
        atomic_write_bytes(paths["svg"], projected)
        accepted, issue = convert_svg_variants(paths["svg"], paths["pdf"], paths["png"])
        if not accepted:
            raise ValueError(issue)
    else:
        raise ValueError("Paper projection supports only trusted quantitative sources and safe deterministic SVGs")
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
        raise ValueError("Paper typography rendering did not produce a complete same-source variant set")
    return paths, template


def _execute_trusted_plot(code: str, source: Path) -> None:
    """Only structurally verified packaged code reaches execution; no subprocess/model."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    prior_figures = set(plt.get_fignums())
    try:
        with matplotlib.rc_context():
            exec(compile(code, str(source), "exec"), {"__file__": str(source), "__name__": "merak_paper_trusted_plot"})
    finally:
        for number in set(plt.get_fignums()) - prior_figures:
            plt.close(number)


def _prepare_matplotlib_cache(source: Path) -> None:
    """Initialize this trusted renderer before optional read-only pixel verification."""
    if source.suffix.casefold() == ".py":
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot
        import matplotlib.font_manager


def _assert_original(root: Path, inputs: dict[str, str]) -> None:
    if any(file_sha256(local_path(root, relative)) != expected for relative, expected in inputs.items()):
        raise ValueError("Original science or source pixels changed during paper typography rendering")


def _packet(root: Path, entry: dict, placement: dict, inputs: dict, inventories: list,
            rounds: list, paths: dict[str, Path], destination: Path, template: bytes) -> dict:
    derived = {kind: (destination / path.name).relative_to(root).as_posix() for kind, path in paths.items()}
    packet = {"schema": 1, "producer": "paper_same_source_typography", "asset_id": destination.name,
              "original_path": entry["output_path"], "source": entry["source_path"],
              "label": str((entry.get("metadata") or {}).get("label") or ""),
              "output_path": derived["pdf"], "source_path": derived["source"],
              "provenance_path": (destination / "PROVENANCE.json").relative_to(root).as_posix(),
              "original_entry_sha256": stable_json_sha256(entry), "original_inputs_sha256": inputs,
              "csv_inventory": inventories, "print_placement": placement,
              "renderer_sha256": _renderer_digest(template), "derived_paths": derived,
              "derived_sha256": {kind: file_sha256(path) for kind, path in paths.items()},
              "render_attempts": rounds, "scientific_data_changed": False, "model_invoked": False}
    packet["input_signature"] = stable_json_sha256({key: packet[key] for key in (
        "original_entry_sha256", "original_inputs_sha256", "print_placement", "renderer_sha256")})
    return packet


def _commit_packet(root: Path, packet: dict, candidates: dict[str, Path], destination: Path) -> None:
    targets = {kind: root / relative for kind, relative in packet["derived_paths"].items()}
    provenance = destination / "PROVENANCE.json"
    before = {path: path.read_bytes() if path.is_file() else None for path in (*targets.values(), provenance)}
    try:
        _assert_original(root, packet["original_inputs_sha256"])
        for kind, target in targets.items():
            atomic_write_bytes(target, candidates[kind].read_bytes())
        atomic_write_json(provenance, packet)
        _assert_original(root, packet["original_inputs_sha256"])
    except BaseException:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, content)
        raise


def validate_derived_figure(root: Path, packet: dict[str, Any]) -> list[str]:
    """Validate current original/derived bytes and actual font geometry, not success flags."""
    try:
        root = root.resolve(strict=True)
        if packet.get("schema") != 1 or packet.get("producer") != "paper_same_source_typography":
            raise ValueError("Paper typography packet schema or producer is unsupported")
        provenance = local_path(root, packet.get("provenance_path"))
        destination = (root / "paper/derived-figures" / str(packet.get("asset_id") or "")).resolve()
        if provenance != destination / "PROVENANCE.json" or not destination.is_relative_to(root / "paper/derived-figures"):
            raise ValueError("Paper typography provenance leaves its declared stable asset owner")
        if json.loads(provenance.read_text(encoding="utf-8-sig")) != packet:
            raise ValueError("Paper typography packet differs from its committed provenance")
        entry = _current_entry(root, str(packet.get("asset_id") or ""))
        bound, inventories = bound_original_inputs(root, entry)
        if (stable_json_sha256(entry) != packet.get("original_entry_sha256")
                or bound != packet.get("original_inputs_sha256") or inventories != packet.get("csv_inventory")
                or packet.get("original_path") != entry.get("output_path") or packet.get("source") != entry.get("source_path")):
            raise ValueError("Paper typography provenance differs from its complete current scientific source inventory")
        _assert_original(root, bound)
        paths, expected = packet.get("derived_paths") or {}, packet.get("derived_sha256") or {}
        if set(paths) != {"source", "pdf", "svg", "png"} or set(paths) != set(expected):
            raise ValueError("Paper typography packet lacks its complete same-source variant inventory")
        for kind, relative in paths.items():
            path = local_path(root, relative)
            if not path.is_relative_to(destination) or file_sha256(path) != expected[kind]:
                raise ValueError("Paper typography variant changed or escaped its derived owner")
        placement = verified_print_placement(root, entry, packet.get("print_placement") or {})
        geometry = pdf_print_geometry(local_path(root, paths["pdf"]), placement)
        if geometry["minimum_placed_font_bp"] < placement["target_font_bp"] or geometry["text_geometry_findings"]:
            raise ValueError("Paper typography variant fails its actual print-scale font or collision checks")
        source = local_path(root, packet["source"])
        template = match_trusted_plot(source.read_text(encoding="utf-8-sig"))[2] if source.suffix == ".py" else source.read_bytes()
        if packet.get("renderer_sha256") != _renderer_digest(template):
            raise ValueError("Paper typography renderer implementation changed after derivation")
        _validate_projected_source(root, packet, source, destination)
        from .paper_derived_pixel_binding import validate_pixel_binding
        pixel_issues = validate_pixel_binding(root, packet)
        if pixel_issues:
            raise ValueError("; ".join(pixel_issues))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        return [str(error)]
    return []


def _current_entry(root: Path, identity: str) -> dict:
    payload = json.loads((root / "figures/FIGURE_MANIFEST.json").read_text(encoding="utf-8-sig"))
    entries = [item for item in payload.get("figures") or [] if isinstance(item, dict)
               and str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or "") == identity]
    if payload.get("schema") != 1 or len(entries) != 1:
        raise ValueError("Paper typography needs one current canonical figure-manifest entry")
    return entries[0]


def _validate_projected_source(root: Path, packet: dict, source: Path, destination: Path) -> None:
    rounds = packet.get("render_attempts")
    if not isinstance(rounds, list) or not 1 <= len(rounds) <= 2:
        raise ValueError("Paper typography provenance has no bounded current render attempts")
    multiplier = rounds[-1].get("font_multiplier")
    derived = local_path(root, packet["source_path"])
    if source.suffix.casefold() == ".py":
        expected = projected_plot_source(source.read_text(encoding="utf-8-sig"), root, destination / "figure", multiplier)[0].encode()
    else:
        expected = _expected_svg(root, source, packet, multiplier)
    actual = derived.read_bytes()
    matches = actual == expected if source.suffix.casefold() == ".py" else canonical_svg_identity(actual) == canonical_svg_identity(expected)
    if not matches:
        raise ValueError("Paper typography source is not the exact authorized same-science projection")
    signature = stable_json_sha256({key: packet[key] for key in (
        "original_entry_sha256", "original_inputs_sha256", "print_placement", "renderer_sha256")})
    if packet.get("input_signature") != signature:
        raise ValueError("Paper typography input signature is not current")


def _projected_svg(original: bytes, multiplier: float) -> bytes:
    if b'id="eval_group_split"' in original and b'id="eval_publication_labels"' in original:
        from .paper_evaluation_svg_layout import reflow_evaluation_svg
        return reflow_evaluation_svg(original, multiplier)
    return scaled_svg_typography(original, multiplier)


def expected_projection_source(root: Path, packet: dict[str, Any]) -> bytes:
    """Expose exact current trusted bytes to the independent in-memory pixel proof."""
    source = local_path(root.resolve(), packet["source"])
    destination = (root.resolve() / "paper/derived-figures" / packet["asset_id"]).resolve()
    multiplier = packet["render_attempts"][-1]["font_multiplier"]
    if source.suffix.casefold() == ".py":
        return projected_plot_source(source.read_text(encoding="utf-8-sig"), root.resolve(), destination / "figure", multiplier)[0].encode()
    return _expected_svg(root.resolve(), source, packet, multiplier)


def _expected_svg(root: Path, source: Path, packet: dict, multiplier: float) -> bytes:
    """Keep canonical JSON as identity while deriving only its verified native SVG."""
    if source.suffix.casefold() == ".json":
        from .paper_figurespec_source import projected_figurespec_svg

        return projected_figurespec_svg(root, _current_entry(root, str(packet["asset_id"])), multiplier)
    return _projected_svg(source.read_bytes(), multiplier)
