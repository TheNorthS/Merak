"""Prove authorized same-science reuse of one archived specialist model audit.

This read-only helper returns a proposed plan and proof, never persists them or
executes a model. Its legacy digest verifies original evidence only; production
preparation and acceptance keep the current canonical scientific-input policy.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from server.services.specialist_catalog import SpecialistSpec, selected_specialists
from server.services.specialist_inputs import canonical_scientific_input_bytes, input_relatives
from scripts.live_snapshot_resume_validation import _config_identity


REPOSITORY = Path(__file__).resolve().parents[1]
_VOLATILE = frozenset({"generated_at", "updated_at", "created_at", "input_bundle_sha256",
                       "simulation_manifest_sha256", "output_bytes", "output_sha256",
                       "source_sha256", "rendered_variant_sha256"})
_INPUT_BINDINGS = frozenset({"source_sha256", "output_sha256", "source_data_sha256", "rendered_variant_sha256"})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Specialist reuse requires object-shaped evidence")
    return value, raw


def _contained(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Specialist reuse requires an explicit artifact path")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Specialist reuse artifact leaves its recorded project")
    return path


def _archived(root: Path, original: Path, run_id: str, suffix: str) -> tuple[dict, bytes]:
    relative = f".merak/runs/{run_id}" + (".json" if suffix == "run" else f".{suffix}.json")
    payload, raw = _object(original / relative)
    archived = root / f".merak/snapshot-source-traces/{run_id}.{suffix}.original.json"
    if archived.read_bytes() != raw or payload.get("run_id") != run_id:
        raise ValueError("Specialist reuse original archive or run identity changed")
    return payload, raw


def _legacy_bytes(path: Path, raw: bytes) -> bytes:
    """Verify the actual old audit digest, without changing any current schema."""
    if path.suffix.casefold() != ".json":
        return raw
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        return raw

    def project(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): project(child) for key, child in item.items()
                    if str(key).casefold() not in _VOLATILE}
        return [project(child) for child in item] if isinstance(item, list) else item

    return json.dumps(project(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _binding_projection(raw: bytes) -> dict[str, Any]:
    """Keep source/data/variant hashes strict even where renderer identity is volatile."""
    value = json.loads(raw.decode("utf-8-sig"))
    bindings: dict[str, Any] = {}

    def collect(item: Any, prefix: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                location = prefix + "/" + str(key)
                if str(key) in _INPUT_BINDINGS:
                    bindings[location] = child
                collect(child, location)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                collect(child, prefix + "/" + str(index))

    collect(value, "")
    return bindings


def _verify_file_binding(root: Path, value: Any, expected: Any) -> None:
    path = _contained(root, value)
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected) or _sha(path.read_bytes()) != expected:
        raise ValueError("Specialist reuse source/data/output file binding is stale")


def _verify_planned_files(root: Path, raw: bytes) -> None:
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("schema") != 5 or not isinstance(payload.get("figures"), list) or not payload["figures"]:
        raise ValueError("Specialist reuse requires the current planned-result figure bundle")
    for figure in payload["figures"]:
        metadata = figure.get("metadata") or {}
        for path_key, hash_key in (("source_path", "source_sha256"), ("output_path", "output_sha256")):
            _verify_file_binding(root, figure.get(path_key), figure.get(hash_key))
        sources, hashes = metadata.get("source_data"), metadata.get("source_data_sha256")
        variants, variant_hashes = metadata.get("rendered_variants"), metadata.get("rendered_variant_sha256")
        if (not isinstance(sources, list) or not sources or not isinstance(hashes, dict)
                or not isinstance(variants, dict) or set(variants) != {"pdf", "svg", "png"}
                or not isinstance(variant_hashes, dict)):
            raise ValueError("Specialist reuse needs complete data and figure variant bindings")
        for relative in sources:
            _verify_file_binding(root, relative, hashes.get(relative))
        for kind, relative in variants.items():
            _verify_file_binding(root, relative, variant_hashes.get(kind))


def _input_equality(root: Path, original: Path, spec: SpecialistSpec, style: dict, options: dict) -> dict:
    header = json.dumps({"family": style.get("family"), "study_archetype": style.get("study_archetype"),
                         "target_venue": style.get("target_venue"),
                         "evidence_mode": "executed" if options.get("run_experiment") is True
                         else options.get("non_experiment_evidence_mode", "design_only"),
                         "spec": spec.as_dict()}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    legacy, source_digest, copy_digest = (hashlib.sha256(header) for _ in range(3))
    source_inputs, copy_inputs, present = {}, {}, 0
    for relative in input_relatives(spec.node_id):
        source, current = original / relative, root / relative
        if source.is_file() != current.is_file() or source.exists() and not source.is_file() or current.exists() and not current.is_file():
            raise ValueError("Specialist reuse scientific input presence changed")
        if not source.is_file():
            source_inputs[relative] = copy_inputs[relative] = None
            continue
        source_raw, copy_raw = source.read_bytes(), current.read_bytes()
        source_canonical = canonical_scientific_input_bytes(source, source_raw)
        copy_canonical = canonical_scientific_input_bytes(current, copy_raw)
        if source_canonical != copy_canonical:
            raise ValueError(f"Specialist reuse scientific input differs: {relative}")
        if source.suffix.casefold() == ".json" and _binding_projection(source_raw) != _binding_projection(copy_raw):
            raise ValueError("Specialist reuse source or data hash declaration changed")
        if relative == "experiments/results/templates/PLANNED_RESULT_MANIFEST.json":
            _verify_planned_files(original, source_raw)
            _verify_planned_files(root, copy_raw)
        present += 1
        for digest, raw in ((legacy, _legacy_bytes(source, source_raw)),
                            (source_digest, source_canonical), (copy_digest, copy_canonical)):
            digest.update(relative.encode("utf-8"))
            digest.update(raw)
        source_inputs[relative] = {"raw_sha256": _sha(source_raw), "canonical_sha256": _sha(source_canonical)}
        copy_inputs[relative] = {"raw_sha256": _sha(copy_raw), "canonical_sha256": _sha(copy_canonical)}
    if not present or source_digest.digest() != copy_digest.digest():
        raise ValueError("Specialist reuse lacks identical current scientific inputs")
    return {"original_legacy_input_digest": legacy.hexdigest(), "current_input_digest": copy_digest.hexdigest(),
            "source_canonical_input_digest": source_digest.hexdigest(),
            "source_inputs": source_inputs, "copy_inputs": copy_inputs}


def _catalog_context(root: Path, original: Path, source_plan: dict, current_plan: dict,
                     source_run: dict, current_run: dict, run_id: str) -> tuple[SpecialistSpec, dict, dict]:
    _config_identity(current_run, source_run, root, original, run_id)
    style, raw = _object(original / "paper/PUBLICATION_STYLE.json")
    current_style, current_raw = _object(root / "paper/PUBLICATION_STYLE.json")
    if (style.get("schema_version") != 2 or current_style.get("schema_version") != 2
            or canonical_scientific_input_bytes(original / "paper/PUBLICATION_STYLE.json", raw)
            != canonical_scientific_input_bytes(root / "paper/PUBLICATION_STYLE.json", current_raw)):
        raise ValueError("Specialist reuse publication style changed")
    options = dict((source_run.get("config") or {}).get("options") or {})
    profile = {"family": style.get("family"), "study_archetype": style.get("study_archetype"),
               "target_venue": style.get("target_venue"), "evidence_mode": options.get("non_experiment_evidence_mode")}
    if (source_plan.get("schema") != 1 or current_plan.get("schema") != 1
            or source_plan.get("profile") != profile or current_plan.get("profile") != profile
            or options.get("run_experiment") is not False or profile["evidence_mode"] != "synthetic_preview"):
        raise ValueError("Specialist reuse profile or execution options changed")
    spec = next((item for item in selected_specialists(str(profile["family"]), str(profile["study_archetype"]))
                 if item.id == "domain-validation" and item.node_id == "results"), None)
    if spec is None:
        raise ValueError("Specialist reuse has no current catalog owner")
    return spec, style, options


def _plan_row(plan: dict, spec: SpecialistSpec, status: str, run_id: str) -> dict:
    rows = plan.get("subnodes")
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                                        or not row["id"].strip() for row in rows)
            or len({row.get("id") for row in rows}) != len(rows)):
        raise ValueError("Specialist reuse refuses malformed or duplicate plan members")
    matches = [row for row in rows if row.get("id") == spec.id]
    if len(matches) != 1 or any(matches[0].get(key) != value for key, value in spec.as_dict().items()):
        raise ValueError("Specialist reuse source owner differs from the current catalog")
    row = matches[0]
    if row.get("status") != status or row.get("run_id") != run_id:
        raise ValueError("Specialist reuse requires an original completed call and current pending row")
    return row


def _model_proof(root: Path, original: Path, run_id: str, source_row: dict, trace: dict) -> dict:
    from server.services.research_specialists import research_specialist_service
    from server.services.skill_execution_trace import verified_model_invocation

    source_path = _contained(original, source_row.get("invocation_trace"))
    if not source_path.is_relative_to(original / ".merak/skill-invocations"):
        raise ValueError("Specialist reuse invocation belongs to a different project")
    raw_call, raw = _object(source_path)
    copied_path = root / source_path.relative_to(original)
    archive = root / ".merak/snapshot-source-traces/specialist-invocations" / source_path.name
    skill = REPOSITORY / "merak-skills/domain-validation/SKILL.md"
    skill_raw, session = skill.read_bytes(), source_row.get("session_id")
    if (copied_path.read_bytes() != raw or archive.read_bytes() != raw
            or raw_call.get("schema") != 1 or raw_call.get("status") != "completed"
            or raw_call.get("policy_loaded") is not True or not isinstance(session, str) or not session.strip()
            or raw_call.get("session_id") != session or raw_call.get("skill") != "domain-validation"
            or Path(str(raw_call.get("project_path") or "")).resolve() != original
            or Path(str(raw_call.get("skill_source") or "")).resolve() != skill.resolve()
            or raw_call.get("skill_sha256") != _sha(skill_raw) or type(raw_call.get("skill_bytes")) is not int
            or raw_call["skill_bytes"] != len(skill_raw) or not skill_raw
            or not re.fullmatch(r"[a-f0-9]{64}", str(raw_call.get("output_sha256") or ""))):
        raise ValueError("Specialist reuse raw invocation lacks identical full-skill model evidence")
    stage = (trace.get("stages") or {}).get("results")
    if not isinstance(stage, dict) or not stage:
        raise ValueError("Specialist reuse requires nonempty original stage execution evidence")
    matches = [item for item in stage.get("invocations") or [] if isinstance(item, dict)
               and item.get("session_id") == session and item.get("skill") == "domain-validation"
               and item.get("role") == "profile_specialist" and item.get("run_id") == run_id
               and item.get("execution_verified") is True and verified_model_invocation(item)]
    if len(matches) != 1 or any(matches[0].get(key) != raw_call.get(key) for key in ("skill_sha256", "skill_bytes", "model_provider", "model_name")):
        raise ValueError("Specialist reuse stage does not attest the original completed model call")
    if any(not str(source_row.get(key) or "").strip() or source_row[key] != raw_call.get(key)
           for key in ("model_provider", "model_name")):
        raise ValueError("Specialist reuse model identity differs from its original invocation")
    artifact = _contained(original, source_row["artifact"])
    copied_artifact = root / artifact.relative_to(original)
    artifact_raw = artifact.read_bytes()
    if (source_row.get("artifact_sha256") != _sha(artifact_raw) or copied_artifact.read_bytes() != artifact_raw
            or not research_specialist_service._artifact_valid(original, source_row)[0]):
        raise ValueError("Specialist reuse original audited artifact changed or is invalid")
    return {"source_model_session_id": session, "raw_invocation_sha256": _sha(raw),
            "artifact_sha256": _sha(artifact_raw), "full_skill_sha256": _sha(skill_raw),
            "full_skill_bytes": len(skill_raw), "copied_invocation_path": str(copied_path),
            "original_model_execution_verified": True}


def prepare_same_science_specialist_reuse(root: Path, original: Path, run_id: str) -> tuple[dict, dict]:
    """Return one provenance-preserving reuse row only after every actual check passes."""
    root, original = root.resolve(), original.resolve()
    if (root == original or root.is_relative_to(original) or original.is_relative_to(root)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id)):
        raise ValueError("Specialist reuse requires distinct same-run source and copy projects")
    source_plan, plan_raw = _archived(root, original, run_id, "specialists")
    source_run, _run_raw = _archived(root, original, run_id, "run")
    source_trace, trace_raw = _archived(root, original, run_id, "skills")
    current_plan, _current_raw = _object(root / f".merak/runs/{run_id}.specialists.json")
    current_run, _ = _object(root / f".merak/runs/{run_id}.json")
    current_trace, _ = _object(root / f".merak/runs/{run_id}.skills.json")
    if (source_run.get("status") != "cancelled" or current_run.get("run_id") != run_id
            or current_plan.get("run_id") != run_id or source_trace.get("schema") != 2
            or current_trace.get("run_id") != run_id or current_trace.get("schema") != 2
            or Path(str(source_trace.get("project_path") or "")).resolve() != original
            or Path(str(current_trace.get("project_path") or "")).resolve() != root
            or (current_trace.get("stages") or {}).get("results") != (source_trace.get("stages") or {}).get("results")):
        raise ValueError("Specialist reuse execution stage or stopped source identity changed")
    spec, style, options = _catalog_context(root, original, source_plan, current_plan, source_run, current_run, run_id)
    source_row = _plan_row(source_plan, spec, "completed", run_id)
    current_row = _plan_row(current_plan, spec, "pending", run_id)
    if {row["id"] for row in source_plan["subnodes"]} != {row["id"] for row in current_plan["subnodes"]}:
        raise ValueError("Specialist reuse plan membership changed")
    inputs = _input_equality(root, original, spec, style, options)
    if source_row.get("input_digest") != inputs["original_legacy_input_digest"]:
        raise ValueError("Specialist reuse recorded source scientific digest is not authentic")
    if not re.fullmatch(r"[a-f0-9]{64}", str(current_row.get("input_digest") or "")):
        raise ValueError("Specialist reuse pending row lacks a declared prior input identity")
    model = _model_proof(root, original, run_id, source_row, source_trace)
    result = copy.deepcopy(current_plan)
    row = next(item for item in result["subnodes"] if item["id"] == spec.id)
    row.update({"status": "reused", "input_digest": inputs["current_input_digest"],
                "artifact_sha256": model["artifact_sha256"], "session_id": "",
                "completed_at": source_row.get("completed_at"), "invocation_trace": "",
                "model_provider": source_row["model_provider"], "model_name": source_row["model_name"],
                "reused_from_run": run_id, "reused_model_session_id": model["source_model_session_id"],
                "reused_invocation_trace": model["copied_invocation_path"]})
    result["plan_digest"] = _sha(json.dumps(result["subnodes"], sort_keys=True, ensure_ascii=False).encode("utf-8"))[:16]
    proof = {"schema": 1, "specialist_id": spec.id, "source_run_id": run_id,
             "source_plan_sha256": _sha(plan_raw), "source_execution_trace_sha256": _sha(trace_raw),
             "pending_prior_input_digest": current_row["input_digest"],
             **inputs, **model, "canonical_input_bytes_equal": True,
             "source_legacy_digest_verified": True, "no_new_model_execution": True,
             "raw_invocation_records_rewritten": False, "scientific_inputs_rewritten": False}
    return result, proof
