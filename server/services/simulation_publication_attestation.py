"""Re-attest current simulation plot provenance without executing or changing data.

Only the deterministic producer may complete its runtime-owned route metadata.
Every current bundle file and existing scientific registration must attest the
same identity first. This is not schema migration or acceptance of old evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, path_lock
from .simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION,
    simulation_manifest_contract_issues,
)
from .simulation_publication_registry import simulation_figure_production_route
from .simulation_presentation_policy import simulation_presentation_fields


MANIFEST_RELATIVE = "experiments/results/simulated/SIMULATION_MANIFEST.json"
_ROUTE_FIELDS = ("figure_nature", "production_strategy", "producer_kind",
                 "composition_owner", "full_svg_authority", "recommended_backend",
                 "recommended_skill")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Simulation publication attestation requires an explicit artifact path")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Simulation publication attestation path escapes its project")
    return path


def _verify(root: Path, relative: Any, expected: Any, *, figure: bool = False) -> None:
    path = _inside(root, relative)
    if figure and not path.is_relative_to(root / "figures/simulated"):
        raise ValueError("Simulation publication artifact is outside its canonical figure directory")
    if not path.is_file() or not expected or _digest(path) != expected:
        raise ValueError(f"Simulation publication attestation hash mismatch: {relative}")


def _current_bundle(root: Path) -> dict[str, Any]:
    payload = json.loads((root / MANIFEST_RELATIVE).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or (
        payload.get("schema") != SIMULATION_MANIFEST_SCHEMA
        or payload.get("renderer_version") != SIMULATION_RENDERER_VERSION
    ):
        raise ValueError("Simulation publication attestation requires the current bundle schema and renderer")
    issues = simulation_manifest_contract_issues(payload)
    if issues:
        raise ValueError("Simulation publication contract failed: " + "; ".join(issues[:8]))
    data, figures = payload["data_files"], payload["figure_files"]
    if (len({item["path"] for item in data}) != len(data)
            or len({item["id"] for item in figures}) != len(figures)):
        raise ValueError("Simulation publication attestation refuses duplicate data or figure IDs")
    for item in data:
        _verify(root, item["path"], item.get("sha256"))
    for record in figures:
        simulation_figure_production_route(record)
        _verify(root, record["source"], record.get("source_sha256"), figure=True)
        if set(record.get("outputs") or {}) != {"pdf", "svg", "png"}:
            raise ValueError("Simulation publication requires exactly the three canonical figure variants")
        for kind, relative in record["outputs"].items():
            _verify(root, relative, (record.get("output_sha256") or {}).get(kind), figure=True)
    return payload


def _canonical_conflicts(root: Path, records: list[dict[str, Any]]) -> None:
    path = root / "figures/FIGURE_SPECS.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(payload, dict) or payload.get("schema") != 4
            or payload.get("production_policy_schema") != 1
            or payload.get("publication_label_schema") != 1):
        raise ValueError("Simulation publication attestation refuses unsupported canonical FigureSpecs")
    specs = payload.get("figures")
    if not isinstance(specs, list) or any(not isinstance(item, dict) for item in specs):
        raise ValueError("Simulation publication attestation requires named canonical FigureSpecs")
    if any(not str(item.get("id") or "").strip() for item in specs) or (
        len({item.get("id") for item in specs}) != len(specs)
    ):
        raise ValueError("Simulation publication attestation refuses duplicate FigureSpecs")
    by_id = {record["id"]: record for record in records}
    for spec in specs:
        record = by_id.get(spec.get("id"))
        if record is not None and any(spec.get(key) != expected for key, expected in
                                     simulation_figure_production_route(record).items()
                                     if key in _ROUTE_FIELDS):
            raise ValueError(f"{record['id']}: simulation producer conflicts with canonical FigureSpec")


def _registration_updates(
    root: Path, payload: dict[str, Any], registry: dict[str, Any], manifest_hash: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records = {item["id"]: item for item in payload["figure_files"]}
    _verify_registration_identity(root, records, registry["figures"])
    profiles = {item.get("semantic_id"): item for item in payload.get("domain_asset_profile") or []}
    entries = [item for item in registry["figures"] if item.get("id") in records]
    if len(entries) != len(records) or len({item["id"] for item in entries}) != len(entries):
        raise ValueError("Simulation publication attestation requires its complete registered figure bundle")
    declared_data = {item["path"]: item["sha256"] for item in payload["data_files"]}
    updates = []
    for entry in entries:
        record, metadata = records[entry["id"]], dict(entry.get("metadata") or {})
        if (entry.get("source_path") != record["source"]
                or entry.get("source_sha256") != record["source_sha256"]
                or entry.get("output_path") != record["outputs"]["pdf"]
                or entry.get("output_sha256") != record["output_sha256"]["pdf"]
                or metadata.get("simulation_manifest_sha256") != manifest_hash
                or metadata.get("simulation_id") != payload.get("simulation_id")
                or metadata.get("evidence_status") != payload.get("evidence_status")
                or metadata.get("producer_kind") != "deterministic"
                or metadata.get("provenance_kind") != "deterministic_simulation_preview"):
            raise ValueError(f"{entry['id']}: simulation registration is not bound to the current bundle")
        sources = metadata.get("source_data")
        hashes = metadata.get("source_data_sha256")
        if not isinstance(sources, list) or not sources or not isinstance(hashes, dict) or any(
            value not in declared_data or hashes.get(value) != declared_data[value] for value in sources
        ):
            raise ValueError(f"{entry['id']}: simulation registration data binding is absent or stale")
        profile = profiles.get(entry["id"])
        if profile is not None and sources != [
            "experiments/results/simulated/" + str(profile.get("data_file") or "")
        ]:
            raise ValueError(f"{entry['id']}: simulation registration refers to a different scientific dataset")
        for key, expected in (("rendered_variants", record["outputs"]),
                              ("rendered_variant_sha256", record["output_sha256"])):
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"{entry['id']}: registered simulation variants conflict with current pixels")
        route = _attested_registration_route(record, metadata)
        if any(key in metadata and metadata[key] is not None and metadata[key] != route[key]
               for key in _ROUTE_FIELDS):
            raise ValueError(f"{entry['id']}: existing simulation producer route conflicts with its owner")
        desired = {**metadata, **route, **simulation_presentation_fields(metadata), "rendered_variants": record["outputs"],
                   "rendered_variant_sha256": record["output_sha256"]}
        if desired != metadata or simulation_presentation_fields(entry).get("description") != entry.get("description"):
            updates.append((entry, desired))
    return updates


def _attested_registration_route(record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Re-attest the producer without resetting the plan-owned generation decision."""
    route = simulation_figure_production_route(record)
    if "generation_policy" in metadata:
        policy = metadata["generation_policy"]
        if not isinstance(policy, str) or policy not in {"generate", "reuse", "skip"}:
            raise ValueError(f"{record['id']}: simulation registration has an invalid generation policy")
        route["generation_policy"] = policy
    return route


def _verify_registration_identity(root: Path, records: dict[str, dict], entries: list[dict]) -> None:
    """Reject identity/path collisions before record replacement can remove assets."""
    owned = {str((root / relative).resolve()).casefold()
             for record in records.values()
             for relative in (record["source"], *record["outputs"].values())}
    if len(owned) != sum(1 + len(record["outputs"]) for record in records.values()):
        raise ValueError("Simulation registration refuses colliding owned artifact paths")
    for entry in entries:
        metadata = entry.get("metadata") or {}
        identity, semantic_key = entry.get("id"), metadata.get("semantic_key")
        if identity in records:
            if semantic_key != identity or metadata.get("managed_by") != "merak":
                raise ValueError(f"{identity}: simulation registration has a conflicting managed identity")
        else:
            paths = [entry.get("source_path"), entry.get("output_path"),
                     *(metadata.get("rendered_variants") or {}).values()]
            if semantic_key in records or any(
                value and str((root / str(value)).resolve()).casefold() in owned for value in paths
            ):
                raise ValueError("Simulation registration collides with an unrelated managed asset")


def _assert_inputs_unchanged(root: Path, payload: dict[str, Any], original: bytes) -> None:
    if (root / MANIFEST_RELATIVE).read_bytes() != original:
        raise RuntimeError("Simulation bundle changed during publication attestation")
    for item in payload["data_files"]:
        _verify(root, item["path"], item["sha256"])
    for record in payload["figure_files"]:
        _verify(root, record["source"], record["source_sha256"], figure=True)
        for kind, relative in record["outputs"].items():
            _verify(root, relative, record["output_sha256"][kind], figure=True)


def attest_existing_simulation_figures(root: Path) -> list[str]:
    """Transactionally re-record only truthful runtime metadata on verified current pixels.

    No CSV, script, output variant, SIMULATION_MANIFEST or scientific status is
    changed. Unsupported/stale/conflicting inputs fail before registry mutation.
    """
    from .figure_artifacts import figure_artifact_registry

    root = root.resolve()
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        return []
    registry_path = root / "figures/FIGURE_MANIFEST.json"
    with path_lock(registry_path):
        original = manifest_path.read_bytes()
        payload = _current_bundle(root)
        _canonical_conflicts(root, payload["figure_files"])
        registry = figure_artifact_registry.load(root / "figures", strict=True)
        if registry.get("schema") != 1:
            raise ValueError("Simulation publication attestation refuses unsupported registry schema")
        updates = _registration_updates(root, payload, registry, _digest(manifest_path))
        if not updates:
            return []
        targets = [registry_path, registry_path.with_suffix(".md")]
        before = {path: path.read_bytes() if path.exists() else None for path in targets}
        try:
            for entry, metadata in updates:
                _assert_inputs_unchanged(root, payload, original)
                figure_artifact_registry.record(
                    output_dir=root / "figures", figure_type=entry["type"],
                    description=simulation_presentation_fields(entry)["description"], output_path=str(root / entry["output_path"]),
                    source_path=str(root / entry["source_path"]), metadata=metadata,
                )
            _assert_inputs_unchanged(root, payload, original)
        except BaseException:
            for path, content in before.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, content)
            raise
    return [entry["id"] for entry, _metadata in updates]
