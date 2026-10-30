"""Process and filesystem operations for deterministic simulation artifacts."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

from .simulation_asset_profile import simulation_asset_profile
from .backend_python_command import local_figure_script_command


PLANNING_FIGURE_TIMEOUT_SECONDS = 180


def _latex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


async def render_simulation_script(script: Path) -> tuple[bool, str]:
    """Execute a plot with a bounded, cancellation-safe child lifetime."""
    try:
        process = subprocess.Popen(
            local_figure_script_command(script),
            cwd=str(script.parents[2]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
    except OSError as exc:
        return False, str(exc)

    communication = asyncio.create_task(asyncio.to_thread(
        process.communicate, timeout=PLANNING_FIGURE_TIMEOUT_SECONDS,
    ))
    try:
        stdout, stderr = await asyncio.shield(communication)
    except subprocess.TimeoutExpired:
        await _stop_render_child(process, communication)
        return False, (
            "planning figure rendering timed out after "
            f"{PLANNING_FIGURE_TIMEOUT_SECONDS}s"
        )
    except asyncio.CancelledError:
        await _stop_render_child(process, communication)
        raise
    except OSError as exc:
        await _stop_render_child(process, communication)
        return False, str(exc)
    if process.returncode:
        output = (stderr or stdout).decode("utf-8", errors="replace")
        return False, output[-1000:]
    return True, ""


async def _stop_render_child(
    process: subprocess.Popen[bytes], communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    """Kill and reap a plot even if its first communicate just timed out."""
    with suppress(ProcessLookupError):
        process.kill()
    with suppress(subprocess.TimeoutExpired, OSError):
        await asyncio.shield(communication)
    await asyncio.to_thread(process.communicate, timeout=5)


def simulation_figures_tex(rendered: list[dict[str, Any]]) -> str:
    blocks = ["% Deterministic simulation benchmark figures"]
    for item in rendered:
        blocks.append("\n".join([
            r"\begin{figure*}[t]",
            r"\centering",
            r"\includegraphics[width=0.94\textwidth]"
            f"{{../figures/simulated/{item['stem']}.pdf}}",
            f"\\caption{{{_latex(str(item['description']))}}}",
            f"\\label{{{item['label']}}}",
            r"\end{figure*}",
        ]))
    return "\n\n".join(blocks) + "\n"


def clear_simulation_preview(root: Path) -> None:
    """Remove only files declared by the managed simulation bundle."""

    simulated_data = root / "experiments" / "results" / "simulated"
    simulated_figures = root / "figures" / "simulated"
    declared = _declared_manifest_paths(root, simulated_data / "SIMULATION_MANIFEST.json")
    for candidate in declared:
        _unlink_inside_root(root, candidate)
    for path in _known_managed_paths(root, simulated_data, simulated_figures):
        if path.is_file():
            path.unlink()


def _declared_manifest_paths(root: Path, manifest_path: Path) -> set[Path]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return set()
    if not isinstance(manifest, dict):
        return set()
    paths = {
        root / str(item["path"])
        for item in manifest.get("data_files") or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    for item in manifest.get("figure_files") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "").strip():
            paths.add(root / str(item["source"]))
        outputs = item.get("outputs")
        if isinstance(outputs, dict):
            paths.update(root / str(path) for path in outputs.values() if str(path).strip())
    for key in ("synthetic_preview_table", "synthetic_preview_figures"):
        if str(manifest.get(key) or "").strip():
            paths.add(root / str(manifest[key]))
    return paths


def _unlink_inside_root(root: Path, candidate: Path) -> None:
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return
    if resolved.is_file():
        resolved.unlink()


def _known_managed_paths(
    root: Path, simulated_data: Path, simulated_figures: Path,
) -> list[Path]:
    archetypes = (
        "algorithm_benchmark", "systems_testbed", "observational_cohort",
        "diagnostic_prognostic", "intervention_trial", "omics_discovery",
        "controlled_experiment", "simulation_modeling", "formal_theory",
        "qualitative_mixed", "generic_empirical",
    )
    slugs = {
        asset["slug"]
        for archetype in archetypes
        for asset in simulation_asset_profile({"study_archetype": archetype})["assets"].values()
    }
    data = [simulated_data / f"{slug}.csv" for slug in sorted(slugs)]
    data.extend([simulated_data / "SIMULATION_MANIFEST.json", simulated_data / "README.md"])
    figures = [
        simulated_figures / f"simulated_{slug}{suffix}"
        for slug in sorted(slugs)
        for suffix in (".py", ".pdf", ".svg", ".png")
    ]
    paper = [
        root / "paper" / "tables" / "synthetic_preview_results.tex",
        root / "paper" / "synthetic_preview_figures.tex",
    ]
    return [*data, *figures, *paper]
