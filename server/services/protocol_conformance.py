"""Source-bound protocol readiness, distinct from code reachability or execution.

This ledger records known mismatches and unvalidated obligations. It never
promotes a self-signed declaration to protocol conformance, authorizes an
experiment, executes research source, or changes numeric evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


LEDGER_RELATIVE = "experiments/PROTOCOL_CONFORMANCE.json"
_AUTHORITY = ("experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json")
_STATES = frozenset({"mismatch", "unvalidated", "corrected_locally"})


class ProtocolConformanceError(ValueError):
    """A declared readiness ledger is stale, unsafe or scientifically overstated."""


@dataclass(frozen=True)
class ProtocolReadiness:
    status: str
    findings: tuple[dict[str, Any], ...]
    source_sha256: dict[str, str]
    cannot_execute: bool = True
    research_evidence: bool = False
    implementation_matches_protocol: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"schema": 1, "status": self.status, "findings": list(self.findings),
                "source_sha256": dict(self.source_sha256), "cannot_execute": self.cannot_execute,
                "research_evidence": self.research_evidence,
                "implementation_matches_protocol": self.implementation_matches_protocol}


def _local_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ProtocolConformanceError("Protocol readiness requires explicit relative local paths")
    unresolved = root / relative
    path = unresolved.resolve()
    if (not path.is_relative_to(root) or path.relative_to(root).as_posix() != relative
            or not path.is_file() or path.stat().st_nlink > 1
            or any(parent.is_symlink() for parent in (unresolved, *unresolved.parents) if parent != root.parent)):
        raise ProtocolConformanceError("Protocol readiness input is missing, linked or outside its owner: " + relative)
    return path


def _sha(root: Path, relative: str) -> str:
    return hashlib.sha256(_local_file(root, relative).read_bytes()).hexdigest()


def _implementation_inventory(root: Path) -> dict[str, str]:
    paths = {"experiments/RUN_SPEC.json"}
    for directory, suffixes in (("experiments/src", {".py"}), ("experiments/tests", {".py"}),
                                ("experiments/configs", {".yaml", ".yml", ".json"})):
        paths.update(path.relative_to(root).as_posix() for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix.casefold() in suffixes)
    if not any(name.startswith("experiments/src/") for name in paths):
        raise ProtocolConformanceError("Protocol readiness requires its actual implementation source inventory")
    return {name: _sha(root, name) for name in sorted(paths)}


def _no_execution_declarations(root: Path, config_relative: str) -> None:
    try:
        config = yaml.safe_load(_local_file(root, config_relative).read_text(encoding="utf-8-sig"))
        run_spec = json.loads(_local_file(root, "experiments/RUN_SPEC.json").read_text(encoding="utf-8-sig"))
        method = json.loads(_local_file(root, "experiments/METHOD_CONTRACT.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise ProtocolConformanceError("Protocol readiness declarations cannot be read") from error
    if not all(isinstance(value, dict) for value in (config, run_spec, method)) or method.get("schema") != 2:
        raise ProtocolConformanceError("Protocol readiness requires current object-shaped method/config/run declarations")
    research, execution = config.get("research_contract") or {}, config.get("execution") or {}
    if (not isinstance(research, dict) or not isinstance(execution, dict)
            or research.get("execution_authorized") is not False
            or execution.get("execution_prohibited_in_this_stage") is not True
            or run_spec.get("run_experiment_authorized") is not False
            or run_spec.get("execution_prohibited_in_this_stage") is not True
            or run_spec.get("execution_status") != "not_executed"):
        raise ProtocolConformanceError("Unvalidated protocol must explicitly prohibit execution in config and RUN_SPEC")


def _findings(values: Any, bound: set[str]) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, list) or not values:
        raise ProtocolConformanceError("Protocol readiness requires explicit unresolved or locally corrected obligations")
    result, identities = [], set()
    for item in values:
        if (not isinstance(item, dict) or set(item) != {"id", "status", "area", "declared", "observed", "evidence"}
                or item.get("status") not in _STATES or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("id", "area", "declared", "observed"))
                or item["id"] in identities or not isinstance(item.get("evidence"), list)
                or not item["evidence"] or any(not isinstance(path, str) or path not in bound for path in item["evidence"])):
            raise ProtocolConformanceError("Protocol readiness finding is unsupported, duplicated or not source-bound")
        identities.add(item["id"])
        result.append({**item, "evidence": list(item["evidence"])})
    return tuple(result)


def build_protocol_conformance_ledger(root: str | Path, findings: list[dict[str, Any]], *,
                                     config_relative: str = "experiments/configs/main.yaml") -> dict[str, Any]:
    """Prepare deterministic negative-readiness evidence; the caller owns persistence."""
    root = Path(root).resolve(strict=True)
    authority = {name: _sha(root, name) for name in _AUTHORITY}
    implementation = _implementation_inventory(root)
    if (not isinstance(config_relative, str) or config_relative not in implementation
            or not config_relative.startswith("experiments/configs/")):
        raise ProtocolConformanceError("Protocol readiness configuration must be in its complete owned inventory")
    _no_execution_declarations(root, config_relative)
    checked = _findings(findings, set(authority) | set(implementation))
    status = "mismatch" if any(item["status"] == "mismatch" for item in checked) else "unvalidated"
    return {"schema": 1, "owner": "protocol_readiness", "status": status,
            "configuration_path": config_relative, "authority_sha256": authority,
            "implementation_sha256": implementation, "findings": list(checked),
            "cannot_execute": True, "research_evidence": False, "implementation_matches_protocol": False}


def validate_protocol_conformance_ledger(root: str | Path, payload: Any) -> ProtocolReadiness:
    """Require exact current bindings; a re-signed ledger cannot claim conformance."""
    expected_keys = {"schema", "owner", "status", "configuration_path", "authority_sha256",
                     "implementation_sha256", "findings", "cannot_execute", "research_evidence",
                     "implementation_matches_protocol"}
    if (not isinstance(payload, dict) or set(payload) != expected_keys or type(payload.get("schema")) is not int
            or payload["schema"] != 1 or payload.get("owner") != "protocol_readiness"
            or payload.get("cannot_execute") is not True or payload.get("research_evidence") is not False
            or payload.get("implementation_matches_protocol") is not False):
        raise ProtocolConformanceError("Protocol ledger cannot authorize execution, assert conformance or claim research evidence")
    actual = build_protocol_conformance_ledger(root, payload["findings"], config_relative=payload["configuration_path"])
    if payload != actual:
        raise ProtocolConformanceError("Protocol readiness source inventory, status or file hashes are stale")
    return ProtocolReadiness(actual["status"], tuple(actual["findings"]),
                             {**actual["authority_sha256"], **actual["implementation_sha256"]})


def _declared_ledger(root: Path) -> bool:
    """An explicit canonical opt-in cannot fall back to legacy absence."""
    relative = "experiments/configs/main.yaml"
    if not (root / relative).is_file():
        return False
    try:
        config = yaml.safe_load(_local_file(root, relative).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise ProtocolConformanceError("Protocol readiness configuration cannot be read") from error
    contract = config.get("research_contract") if isinstance(config, dict) else None
    if not isinstance(contract, dict) or "protocol_conformance_path" not in contract:
        return False
    if contract["protocol_conformance_path"] != LEDGER_RELATIVE:
        raise ProtocolConformanceError("Declared protocol readiness ledger must use its canonical owned path")
    return True


def read_protocol_readiness(root: str | Path) -> ProtocolReadiness | None:
    """Absence preserves legacy behavior but is not proof of protocol readiness."""
    root = Path(root).resolve()
    declared = _declared_ledger(root)
    path = root / LEDGER_RELATIVE
    if not path.exists() and not path.is_symlink():
        if declared:
            raise ProtocolConformanceError("Declared protocol readiness ledger is missing; scientific execution remains prohibited")
        return None
    try:
        payload = json.loads(_local_file(root, LEDGER_RELATIVE).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ProtocolConformanceError("Present protocol readiness ledger is invalid: " + str(error)) from error
    return validate_protocol_conformance_ledger(root, payload)


def require_protocol_execution_readiness(project_path: str) -> None:
    """Refuse a present negative-readiness ledger before scheduling any work."""
    if project_path and read_protocol_readiness(project_path) is not None:
        raise ProtocolConformanceError("Protocol implementation is unvalidated or mismatched; scientific execution is prohibited")


def protocol_readiness_prompt(root: str | Path) -> str:
    """Separate a proposed paper protocol from verified or executed implementation."""
    try:
        value = read_protocol_readiness(root)
    except ProtocolConformanceError as error:
        return "\n\n## Protocol readiness\nBLOCKED: " + str(error) + ". Cannot execute or claim implementation conformance."
    if value is None:
        return "\n\n## Protocol readiness\nNo protocol-conformance ledger: readiness is not validated; absence is not implementation_matches_protocol evidence."
    return ("\n\n## Protocol readiness\nThe manuscript may describe the proposed protocol and its independently bound "
            "evidence track, but this implementation is not protocol-conformant research evidence. Do not claim "
            "training, successful execution or implementation_matches_protocol. Execution is prohibited.\n```json\n"
            + json.dumps(value.to_dict(), ensure_ascii=False, sort_keys=True) + "\n```")


def overlapping_subset_counts(population: int, requested_size: int, requested_overlap: int, *,
                              minimum_population: int, minimum_size: int,
                              size_fraction: tuple[int, int], overlap_fraction: tuple[int, int]) -> tuple[int, int]:
    """Check an explicitly supplied integer policy; zero alone means automatic."""
    if (not isinstance(size_fraction, tuple) or len(size_fraction) != 2
            or not isinstance(overlap_fraction, tuple) or len(overlap_fraction) != 2):
        raise ProtocolConformanceError("Subset fractions require explicit integer numerator/denominator pairs")
    values = (population, requested_size, requested_overlap, minimum_population, minimum_size,
              *size_fraction, *overlap_fraction)
    if (any(type(value) is not int for value in values) or requested_size < 0 or requested_overlap < 0
            or minimum_population < 1 or minimum_size < 1 or population < minimum_population
            or not 0 < size_fraction[0] <= size_fraction[1]
            or not 0 < overlap_fraction[0] < overlap_fraction[1]):
        raise ProtocolConformanceError("Subset arithmetic requires an eligible population and an explicit valid integer policy")
    size = requested_size or max(minimum_size, population * size_fraction[0] // size_fraction[1])
    numerator, denominator = overlap_fraction
    overlap = requested_overlap or (size * numerator + denominator - 1) // denominator
    if not 0 < overlap < size <= population or 2 * size - overlap > population:
        raise ProtocolConformanceError("Subset policy requires 0 < overlap < size <= population and 2*size-overlap <= population")
    return size, overlap


def stable_identity_seed(run_seed: int, identity: str) -> int:
    """Derive a bounded RNG seed from an explicit stable ID, never list order."""
    if type(run_seed) is not int or not isinstance(identity, str) or not identity.strip():
        raise ProtocolConformanceError("Stable sampling requires an integer run seed and a nonempty source identity")
    digest = hashlib.sha256(f"{run_seed}:{identity}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
