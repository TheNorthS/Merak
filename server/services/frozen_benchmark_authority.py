"""Read-only authority for unchanged structural benchmarks beside prospective code.

The caller supplies independently pinned historical inputs, frozen benchmark
files and current code inputs. This proof does not re-sign PLANNED/SIMULATION
manifests, regenerate figures or numbers, grant workflow acceptance, or claim
that a historical structural simulator executed the prospective implementation.
The historical six raw input files remain generation authority. Fresh owner
reports belong to a separately pinned current context, never a substitute for
the archived reports used when the benchmark was originally generated.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .experiment_placeholder_context import _method_fields, input_bundle_sha256
from .protocol_conformance import read_protocol_readiness
from .simulation_publication_attestation import _current_bundle


PROOF_RELATIVE = "experiments/FROZEN_BENCHMARK_AUTHORITY.json"
_INPUTS = ("ideas/ideas.md", "ideas/novelty_report.md", "ideas/SELECTED_IDEA.json",
           "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json", "experiments/configs/main.yaml")
_PLANNED = "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
_SIMULATION = "experiments/results/simulated/SIMULATION_MANIFEST.json"
_READINESS = "experiments/PROTOCOL_CONFORMANCE.json"
_CODE = "experiments/CODE_IMPLEMENTATION_ATTESTATION.json"
_METHOD_IMPLEMENTATION = frozenset({"implementation_checks", "implementation_evidence_register",
                                   "implementation_level", "code_validation_level", "scientific_execution_performed",
                                   "scientific_scene", "status"})
_SETTINGS = frozenset({"direction", "evidence_mode", "target_venue", "research_family", "study_archetype"})


class FrozenBenchmarkAuthorityError(ValueError):
    """Historical generation authority or immutable evidence cannot be established."""


def _path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise FrozenBenchmarkAuthorityError("Frozen authority requires canonical relative paths")
    candidate, path = root / relative, (root / relative).resolve()
    if (not path.is_relative_to(root) or path.relative_to(root).as_posix() != relative
            or not path.is_file() or path.stat().st_nlink > 1
            or any(parent.is_symlink() for parent in (candidate, *candidate.parents))):
        raise FrozenBenchmarkAuthorityError("Frozen authority source is missing, linked or foreign: " + relative)
    return path


def _hash(root: Path, relative: str) -> str:
    return hashlib.sha256(_path(root, relative).read_bytes()).hexdigest()


def _json(root: Path, relative: str) -> dict:
    try:
        payload = json.loads(_path(root, relative).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise FrozenBenchmarkAuthorityError("Frozen authority cannot read an object: " + relative) from error
    if not isinstance(payload, dict):
        raise FrozenBenchmarkAuthorityError("Frozen authority requires object-shaped metadata: " + relative)
    return payload


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _settings(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != _SETTINGS
            or any(not isinstance(item, str) for item in value.values())
            or value["evidence_mode"] != "synthetic_preview" or not value["direction"].strip()):
        raise FrozenBenchmarkAuthorityError("Frozen authority is restricted to explicitly selected structural synthetic evidence")
    return {key: value[key].strip() for key in sorted(value)}


def _input_digest(root: Path, settings: dict) -> str:
    return input_bundle_sha256(root, settings["direction"], **{key: value for key, value in settings.items() if key != "direction"})


def historical_inputs_digest(root: Path, settings: dict) -> str:
    """Observe an external historical pin; its six raw generation inputs must exist."""
    root, settings = root.resolve(strict=True), _settings(settings)
    return _digest({"settings": settings, "files": {name: _hash(root, name) for name in (*_INPUTS, "experiments/RUN_SPEC.json")}})


def benchmark_inventory(root: Path) -> dict[str, str]:
    """Bind all frozen numeric/provenance/template/plot files, including unknown additions."""
    root = root.resolve(strict=True)
    paths = {path.relative_to(root).as_posix()
             for directory in ("experiments/results/simulated", "experiments/results/templates", "figures/simulated")
             for path in (root / directory).rglob("*") if path.is_file()}
    paths.update(path.relative_to(root).as_posix() for directory in ("experiments/results", "paper/tables")
                 for path in (root / directory).rglob("*.csv") if path.is_file())
    if not {_PLANNED, _SIMULATION} <= paths or not any(name.endswith(".csv") for name in paths):
        raise FrozenBenchmarkAuthorityError("Frozen benchmark lacks its manifests and numerical inventory")
    return {name: _hash(root, name) for name in sorted(paths)}


def benchmark_inventory_digest(root: Path) -> str:
    return _digest(benchmark_inventory(root))


def prospective_inventory_digest(root: Path) -> str:
    """Pin future code and fresh owner reports, without making them past provenance."""
    root = root.resolve(strict=True)
    paths = {"experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", _READINESS, _CODE,
             *current_owner_report_context(root)}
    for directory, suffixes in (("experiments/src", {".py"}), ("experiments/tests", {".py"}),
                                ("experiments/configs", {".json", ".yaml", ".yml"})):
        paths.update(path.relative_to(root).as_posix() for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix.casefold() in suffixes)
    if not any(name.startswith("experiments/src/") for name in paths):
        raise FrozenBenchmarkAuthorityError("Prospective implementation has no source identity")
    return _digest({name: _hash(root, name) for name in sorted(paths)})


def current_owner_report_context(root: Path) -> dict[str, str]:
    """Capture new literature/idea/novelty context; validation still belongs to its owners."""
    root = root.resolve(strict=True)
    paths = set(_INPUTS[:2])
    paths.update(path.relative_to(root).as_posix() for path in (root / "literature").rglob("*")
                 if path.is_file() and path.suffix.casefold() in {".md", ".json", ".bib", ".txt", ".csv"})
    return {name: _hash(root, name) for name in sorted(paths)}


def _scientific_method(value: dict) -> dict:
    if type(value.get("schema")) is not int or value["schema"] != 2:
        raise FrozenBenchmarkAuthorityError("Frozen authority requires current method schema 2")
    if value.get("scientific_execution_performed") is not None and value.get("scientific_execution_performed") is not False:
        raise FrozenBenchmarkAuthorityError("Prospective code cannot claim scientific execution")
    result = {key: copy.deepcopy(item) for key, item in value.items() if key not in _METHOD_IMPLEMENTATION}
    if "integration_verdict" in result:
        verdict = result["integration_verdict"]
        if (not isinstance(verdict, dict) or not isinstance(verdict.get("output_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", verdict["output_sha256"])):
            raise FrozenBenchmarkAuthorityError("Method integration_verdict requires its current deterministic SHA-256")
        # Only this producer-owned digest changes when the same frozen science
        # passes current implementation integration. Validator and extra fields
        # remain bound; ignoring this digest is not workflow acceptance.
        del verdict["output_sha256"]
    coverage = result.get("mechanism_coverage")
    if not isinstance(coverage, list) or any(not isinstance(item, dict) for item in coverage):
        raise FrozenBenchmarkAuthorityError("Method mechanism coverage is absent or malformed")
    result["mechanism_coverage"] = [{key: item for key, item in row.items()
                                     if key not in {"implementation_check_ids", "status"}} for row in coverage]
    return result


def _unchanged_science(root: Path, history: Path) -> None:
    for name in _INPUTS[2:4]:
        if _path(root, name).read_bytes() != _path(history, name).read_bytes():
            raise FrozenBenchmarkAuthorityError("Prospective code changed selected claims, public labels or registered plan: " + name)
    current, previous = _json(root, _INPUTS[4]), _json(history, _INPUTS[4])
    if _method_fields(current) != _method_fields(previous) or _scientific_method(current) != _scientific_method(previous):
        raise FrozenBenchmarkAuthorityError("Prospective method changed generator semantics, mechanism, claims or evaluation semantics")
    if current.get("scientific_scene") != previous.get("scientific_scene"):
        _current_scene(root, current.get("scientific_scene"))


def _current_scene(root: Path, scene: Any) -> None:
    """A revised future-method scene needs source bindings; it is not old simulation input."""
    from .scientific_scene import validate_scientific_scene

    issues = validate_scientific_scene(scene)
    if issues:
        raise FrozenBenchmarkAuthorityError("Prospective method scene is invalid: " + "; ".join(issues[:8]))
    for node in scene["objects"]:
        relative = node["source_path"]
        if not isinstance(relative, str):
            raise FrozenBenchmarkAuthorityError("Prospective scene source path must be canonical text")
        allowed = relative in {"ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md"} or relative.startswith("experiments/src/")
        if not allowed or node.get("source_sha256") != _hash(root, relative):
            raise FrozenBenchmarkAuthorityError("Prospective scene object lacks a current owned source binding: " + node["id"])


def _historical_generation(history: Path, reference: Path, simulation: dict, planned: dict, settings: dict) -> str:
    old_digest = _input_digest(history, settings)
    if (planned.get("schema") != 5 or planned.get("evidence_mode") != "synthetic_preview"
            or planned.get("input_bundle_sha256") != old_digest
            or (planned.get("publication_style") or {}).get("target_venue") != settings["target_venue"]):
        raise FrozenBenchmarkAuthorityError("Historical raw inputs/options do not recreate the original planned generation digest")
    package = simulation.get("evidence_package") or {}
    parameters = _json(reference, str(package.get("scenario_parameters") or ""))
    originals = parameters.get("input_files")
    names = ("experiments/configs/main.yaml", "experiments/RUN_SPEC.json", "experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json")
    if (originals != {name: _hash(history, name) for name in names}
            or parameters.get("simulation_id") != simulation.get("simulation_id")
            or str(parameters.get("simulation_seed")) != str(simulation.get("simulation_seed"))
            or parameters.get("replicate_seeds") != simulation.get("replicate_contract", {}).get("seed_ids")
            or parameters.get("registered_models") != simulation.get("registered_model_suite")
            or parameters.get("registered_axes") != simulation.get("registered_ranking_axes")):
        raise FrozenBenchmarkAuthorityError("Original simulator registration does not bind these historical inputs, seeds and model suite")
    for key, name in (("scenario_config", names[0]), ("run_spec", names[1]), ("method_contract", names[2])):
        archived = _path(reference, str(package.get(key) or ""))
        if _hash(reference, archived.relative_to(reference).as_posix()) != package.get(key + "_sha256"):
            raise FrozenBenchmarkAuthorityError("Historical simulator input snapshot has a stale recorded hash")
        if key == "scenario_config":
            same = archived.read_bytes() == _path(history, name).read_bytes()
        else:
            same = _json(reference, archived.relative_to(reference).as_posix()) == _json(history, name)
        if not same:
            raise FrozenBenchmarkAuthorityError("Historical simulator snapshot differs from its original source input")
    return old_digest


def _prospective_scope(root: Path, simulation: dict) -> dict:
    readiness = read_protocol_readiness(root)
    code, run = _json(root, _CODE), _json(root, "experiments/RUN_SPEC.json")
    if (readiness is None or not readiness.cannot_execute or type(code.get("schema")) is not int or code.get("schema") != 1
            or code.get("validation_level") != "V1_pure_local" or code.get("code_ready_verified") is not True
            or any(code.get(name) is not False for name in ("scientific_execution_performed", "training_performed",
                                                          "research_evidence", "experiment_authorized"))
            or run.get("seeds") != simulation.get("replicate_contract", {}).get("seed_ids")
            or (run.get("scientific_outputs") or {}).get("primary_metric") != simulation.get("primary_metric")):
        raise FrozenBenchmarkAuthorityError("Prospective code has no separate nonexecuted source/metric/seed readiness scope")
    sources = code.get("source_sha256")
    if not isinstance(sources, dict) or not sources or any(_hash(root, name) != digest for name, digest in sources.items()):
        raise FrozenBenchmarkAuthorityError("Prospective code attestation does not bind its current source bytes")
    return {"protocol_id": str(run.get("protocol_id") or ""), "execution_status": "not_executed",
            "implementation_is_benchmark_generator": False, "code_is_empirical_evidence": False,
            "source_attestation_sha256": _hash(root, _CODE), "readiness_status": readiness.status}


def prepare_frozen_benchmark_authority(root: Path, historical_inputs: Path, frozen_reference: Path, settings: dict, *,
                                      historical_inputs_pin: str, benchmark_inventory_pin: str,
                                      prospective_inventory_pin: str, current_input_digest: str) -> dict[str, Any]:
    """Construct provenance only after all three independently pinned owners pass."""
    root, history, reference = (path.resolve(strict=True) for path in (root, historical_inputs, frozen_reference))
    settings = _settings(settings)
    pins = (historical_inputs_pin, benchmark_inventory_pin, prospective_inventory_pin, current_input_digest)
    if (root == history or root == reference or any(not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin) for pin in pins)
            or historical_inputs_digest(history, settings) != historical_inputs_pin
            or benchmark_inventory_digest(reference) != benchmark_inventory_pin
            or prospective_inventory_digest(root) != prospective_inventory_pin
            or _input_digest(root, settings) != current_input_digest):
        raise FrozenBenchmarkAuthorityError("Frozen benchmark authority differs from its independently observed owner pins")
    simulation, original_simulation = _current_bundle(root), _current_bundle(reference)
    current_inventory, original_inventory = benchmark_inventory(root), benchmark_inventory(reference)
    if simulation != original_simulation or current_inventory != original_inventory:
        raise FrozenBenchmarkAuthorityError("Frozen benchmark numeric, provenance, plot or manifest bytes changed")
    planned = _json(reference, _PLANNED)
    old_digest = _historical_generation(history, reference, simulation, planned, settings)
    _unchanged_science(root, history)
    prospective = _prospective_scope(root, simulation)
    current_method = _json(root, "experiments/METHOD_CONTRACT.json")
    prospective["scientific_scene_sha256"] = _digest(current_method.get("scientific_scene"))
    prospective["scene_is_historical_benchmark_input"] = False
    prospective["generator_method_semantics_sha256"] = _digest(_method_fields(current_method))
    if (historical_inputs_digest(history, settings) != historical_inputs_pin
            or benchmark_inventory_digest(root) != benchmark_inventory_pin
            or prospective_inventory_digest(root) != prospective_inventory_pin):
        raise FrozenBenchmarkAuthorityError("Frozen authority owners changed during read-only inspection")
    return {"schema": 1, "owner": "frozen_structural_benchmark_authority", "settings": settings,
            "historical_inputs_root": str(history), "frozen_reference_root": str(reference), "project_root": str(root),
            "historical_inputs_sha256": historical_inputs_pin, "benchmark_inventory_sha256": benchmark_inventory_pin,
            "prospective_inventory_sha256": prospective_inventory_pin, "original_generation_input_sha256": old_digest,
            "current_prospective_input_sha256": current_input_digest,
            "current_owner_report_context": current_owner_report_context(root),
            "reports_were_used_for_historical_generation": False,
            "generation_inputs_are_archived_not_current_context": True,
            "benchmark_scope": {"simulation_id": simulation["simulation_id"], "simulation_seed": simulation["simulation_seed"],
                                "registered_model_suite": simulation["registered_model_suite"],
                                "replicate_contract": simulation["replicate_contract"], "primary_metric": simulation["primary_metric"],
                                "metric_direction": simulation["metric_direction"], "evidence_mode": "synthetic_preview"},
            "prospective_scope": prospective, "original_planned_manifest_sha256": _hash(root, _PLANNED),
            "original_simulation_manifest_sha256": _hash(root, _SIMULATION), "numeric_and_provenance_files_unchanged": True,
            "manifests_resigned": False, "scientific_execution_performed": False, "workflow_acceptance_granted": False}


def validate_frozen_benchmark_authority(root: Path, payload: Any, historical_inputs: Path, frozen_reference: Path,
                                       settings: dict, *, historical_inputs_pin: str, benchmark_inventory_pin: str,
                                       prospective_inventory_pin: str, current_input_digest: str) -> dict[str, Any]:
    """Reconstruct exact proof using caller pins, never trust self-signed booleans."""
    actual = prepare_frozen_benchmark_authority(root, historical_inputs, frozen_reference, settings,
        historical_inputs_pin=historical_inputs_pin, benchmark_inventory_pin=benchmark_inventory_pin,
        prospective_inventory_pin=prospective_inventory_pin, current_input_digest=current_input_digest)
    if not isinstance(payload, dict) or payload != actual:
        raise FrozenBenchmarkAuthorityError("Frozen benchmark proof is stale, forged or bound to different scope/owners")
    return actual
