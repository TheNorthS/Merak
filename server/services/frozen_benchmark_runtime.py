"""Runtime commit and read-only validation of explicitly scoped benchmark reuse.

Generation history stays pinned to independently observed original inputs and
frozen files. Current owner-produced reports/code are a different context; a
fresh commit records that difference, never relabels historical measurements.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json, path_lock
from .frozen_benchmark_authority import (
    PROOF_RELATIVE, FrozenBenchmarkAuthorityError, prepare_frozen_benchmark_authority,
    prospective_inventory_digest, validate_frozen_benchmark_authority,
)


def _arguments(context: dict) -> dict:
    required = {"schema", "historical_inputs_root", "frozen_reference_root", "historical_inputs_pin",
                "benchmark_inventory_pin", "settings", "prospective_inventory_pin"}
    if not isinstance(context, dict) or set(context) != required or context["schema"] != 1:
        raise FrozenBenchmarkAuthorityError("Benchmark reuse needs explicit independently pinned source authority")
    return {"historical_inputs": Path(context["historical_inputs_root"]),
            "frozen_reference": Path(context["frozen_reference_root"]), "settings": context["settings"],
            "historical_inputs_pin": context["historical_inputs_pin"],
            "benchmark_inventory_pin": context["benchmark_inventory_pin"],
            "prospective_inventory_pin": context["prospective_inventory_pin"]}


def commit_authority(root: Path, context: dict, input_hash: str) -> dict:
    """Caller observes a completed producer transaction; no workflow verdict is created."""
    arguments = _arguments(context)
    if prospective_inventory_digest(root) != arguments["prospective_inventory_pin"]:
        raise FrozenBenchmarkAuthorityError("Current prospective owner changed before explicit authority commit")
    proof = prepare_frozen_benchmark_authority(root, current_input_digest=input_hash, **arguments)
    path = root / PROOF_RELATIVE
    with path_lock(path):
        atomic_write_json(path, proof)
    return proof


def validate_reuse_authority(root: Path, context: dict, input_hash: str) -> dict:
    """A consumer cannot update stale pins or invent an original generation identity."""
    arguments = _arguments(context)
    try:
        payload = json.loads((root / PROOF_RELATIVE).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FrozenBenchmarkAuthorityError("Explicit benchmark authority proof is missing or unreadable") from error
    return validate_frozen_benchmark_authority(root, payload, current_input_digest=input_hash, **arguments)
