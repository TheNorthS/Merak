"""Freeze inspectable inputs and a verifier for deterministic simulation bundles."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, atomic_write_text


def materialize_reproducibility_bundle(
    root: Path, simulated_data: Path, *, generator_source: Path,
    simulation_id: str, simulation_seed: str, seed_ids: list[int],
    method_records: list[tuple[str, str]], registered_axes: list[dict[str, Any]],
    holm_family_size: int, holm_alpha: float,
) -> dict[str, Path]:
    directory = simulated_data / "reproducibility"
    directory.mkdir(parents=True, exist_ok=True)
    paths = _input_paths(root, directory)
    atomic_write_bytes(
        paths["generator_source.py"],
        _generator_source_path(generator_source).read_bytes(),
    )
    _write_input_snapshots(paths)
    atomic_write_json(paths["scenario_parameters.json"], {
        "schema": 1, "simulation_id": simulation_id,
        "simulation_seed": simulation_seed, "replicate_seeds": list(seed_ids),
        "registered_models": [
            {"method": method, "model_id": model_id}
            for method, model_id in method_records
        ],
        "registered_axes": registered_axes,
        "holm_family": {
            "scope": "unordered_model_pairs_by_non_iid_target_axis",
            "size": holm_family_size, "alpha": holm_alpha,
            "test": "paired_student_t_two_sided",
        },
        "input_files": {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in _source_inputs(paths) if path.is_file()
        },
    })
    verifier_template = Path(__file__).with_name(
        "simulation_plot_templates"
    ) / "verify_bundle.py.tmpl"
    atomic_write_text(
        paths["verify_bundle.py"], verifier_template.read_text(encoding="utf-8"),
    )
    return {
        label: path for label, path in paths.items()
        if label in {
            "generator_source.py", "scenario_parameters.json", "verify_bundle.py",
            "scenario_config.yaml", "run_spec.json", "method_contract.json",
        } and path.is_file()
    }


def _generator_source_path(generator_source: Path) -> Path:
    """Use the exact bundled canonical generator source in frozen builds."""
    if not getattr(sys, "frozen", False):
        return generator_source
    if generator_source != Path(__file__).with_name("simulation_benchmark.py"):
        return generator_source
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not isinstance(bundle_root, str) or not bundle_root:
        raise RuntimeError("frozen simulation generator is missing its bundle resource root")
    source = Path(bundle_root) / "merak-source" / "server" / "services" / "simulation_benchmark.py"
    if not source.is_file():
        raise RuntimeError("frozen simulation generator source snapshot is unavailable")
    return source


def _input_paths(root: Path, directory: Path) -> dict[str, Path]:
    return {
        "generator_source.py": directory / "generator_source.py",
        "scenario_parameters.json": directory / "scenario_parameters.json",
        "verify_bundle.py": directory / "verify_bundle.py",
        "scenario_config.yaml": directory / "scenario_config.yaml",
        "run_spec.json": directory / "run_spec.json",
        "method_contract.json": directory / "method_contract.json",
        "source_config": root / "experiments" / "configs" / "main.yaml",
        "source_run_spec": root / "experiments" / "RUN_SPEC.json",
        "source_method_contract": root / "experiments" / "METHOD_CONTRACT.json",
        "source_selected_idea": root / "ideas" / "SELECTED_IDEA.json",
    }


def _write_input_snapshots(paths: dict[str, Path]) -> None:
    config = paths["source_config"]
    atomic_write_text(
        paths["scenario_config.yaml"],
        config.read_text(encoding="utf-8") if config.is_file() else "{}\n",
    )
    for output_key, source_key in (
        ("run_spec.json", "source_run_spec"),
        ("method_contract.json", "source_method_contract"),
    ):
        source = paths[source_key]
        try:
            import json
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        atomic_write_json(paths[output_key], payload if isinstance(payload, dict) else {})


def _source_inputs(paths: dict[str, Path]) -> list[Path]:
    return [paths[key] for key in (
        "source_config", "source_run_spec", "source_method_contract",
        "source_selected_idea",
    )]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
