"""Repair cropped labels only in exact trusted plots, preserving frozen scientific rows."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

from ..utils.atomic_write import atomic_write_text
from .figure_artifacts import figure_artifact_registry
from .paper_trusted_plot_source import match_trusted_plot
from .simulation_plot_layout import wrap_plot_axis_text


def _plot_source_binding(parameters: dict, record: dict, payload: dict) -> str:
    """Require canonical relative paths before any staged write or script execution."""
    stem = parameters.get("stem", parameters.get("output_stem"))
    if not isinstance(stem, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", stem):
        raise ValueError("Plot layout repair output stem is invalid")
    if record["source"] != f"figures/simulated/{stem}.py" or record["outputs"] != {
        kind: f"figures/simulated/{stem}.{kind}" for kind in ("pdf", "svg", "png")
    }:
        raise ValueError("Plot layout repair output differs from its canonical source")
    data = str(parameters["data_path"])
    if (data not in {item["path"] for item in payload["data_files"]}
            or not re.fullmatch(r"experiments/results/simulated/[A-Za-z0-9_-]+\.csv", data)):
        raise ValueError("Plot layout repair input is outside frozen canonical data")
    return data


async def refresh_cropped_plot_labels(root: Path, render_script: Callable[[Path], Awaitable[tuple[bool, str]]]) -> list[str]:
    from . import simulation_figure_refresh as refresh
    from .planned_simulation_bindings import load_planned_simulation_binding

    root = root.resolve()
    manifest = root / refresh._MANIFEST
    if not manifest.is_file():
        return []
    changed = []
    identities = [item["id"] for item in json.loads(manifest.read_bytes())["figure_files"]
                  if item["id"] != refresh._PRIMARY_ID]
    for identity in identities:
        original = manifest.read_bytes()
        payload, _primary = refresh._load_current(root)
        record = next(item for item in payload["figure_files"] if item["id"] == identity)
        if not figure_artifact_registry.raster_layout_issues(root / record["outputs"]["png"]):
            continue
        source = (root / record["source"]).read_text(encoding="utf-8-sig")
        try:
            _name, parameters, _template = match_trusted_plot(source)
        except (SyntaxError, ValueError):
            # Unknown programs remain blocked by the ordinary gate, never executed here.
            continue
        code = wrap_plot_axis_text(source)
        if code.encode("utf-8") == (root / record["source"]).read_bytes():
            continue
        data = _plot_source_binding(parameters, record, payload)
        planned = load_planned_simulation_binding(root, refresh._digest(manifest), payload["figure_files"])
        refresh._verified_registration(root, payload, refresh._digest(manifest))
        transactions = root / ".merak/transactions"
        transactions.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="plot-labels-", dir=transactions) as directory:
            stage = Path(directory)
            target_data = stage / data
            target_data.parent.mkdir(parents=True)
            shutil.copy2(root / data, target_data)
            script = stage / record["source"]
            atomic_write_text(script, code)
            success, error = await render_script(script)
            if not success:
                raise RuntimeError(f"Plot label rendering failed for {identity}: {error}")
            if any(not (stage / path).is_file() or not (stage / path).stat().st_size
                   for path in record["outputs"].values()):
                raise ValueError(f"Plot label rendering has incomplete variants: {identity}")
            issues = figure_artifact_registry.raster_visual_quality_issues(stage / record["outputs"]["png"])
            if issues:
                raise ValueError(f"Plot label rendering rejected for {identity}: " + "; ".join(issues))
            refresh._commit(root, stage, payload, record, original, code, planned)
        changed.append(identity)
    return changed
