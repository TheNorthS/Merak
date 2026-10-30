"""Finite audit-reuse proofs never execute models, promote statuses or write projects."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import live_snapshot_specialist_reuse as service
from server.services.specialist_catalog import selected_specialists
from server.services.specialist_inputs import input_relatives, specialist_input_digest


RUN_ID = "source-run"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _planned(root: Path) -> None:
    figures = []
    for index in range(7):
        data = f"experiments/results/simulated/result_{index}.csv"
        source = f"figures/simulated/result_{index}.py"
        variants = {kind: f"figures/simulated/result_{index}.{kind}" for kind in ("pdf", "svg", "png")}
        for relative in (data, source, *variants.values()):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Finite source/data/output identity fixture; never execute\n")
        figures.append({"id": f"result_{index}", "source_path": source, "source_sha256": _sha((root / source).read_bytes()),
                        "output_path": variants["pdf"], "output_sha256": _sha((root / variants["pdf"]).read_bytes()),
                        "metadata": {"paper_selected": True, "source_data": [data],
                                     "source_data_sha256": {data: _sha((root / data).read_bytes())},
                                     "rendered_variants": variants,
                                     "rendered_variant_sha256": {kind: _sha((root / relative).read_bytes()) for kind, relative in variants.items()}}})
    _write(root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json", {"schema": 5, "figures": figures})


def _inputs(root: Path) -> None:
    _write(root / "ideas/SELECTED_IDEA.json", {"schema": 2, "claims": [{"id": "C1", "statement": "A finite local hypothesis."}]})
    _write(root / "experiments/METHOD_CONTRACT.json", {"schema": 2, "mechanisms": [{"id": "M1", "definition": "Finite local definition"}]})
    for relative in ("literature/survey.md", "literature/references.bib", "experiments/EXPERIMENT_PLAN.md",
                     "experiments/configs/main.yaml", "experiments/results/analysis.md", "experiments/results/templates/README.md"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Finite scientific input fixture\n")
    _write(root / "experiments/RUN_SPEC.json", {"schema": 2, "unit": "fixture", "count": 2})
    _planned(root)


def _old_digest(root: Path, style: dict, spec, options: dict) -> str:
    """Reproduce the pre-selection-projection owner calculation independently."""
    volatile = {"generated_at", "updated_at", "created_at", "input_bundle_sha256", "simulation_manifest_sha256",
                "output_bytes", "output_sha256", "source_sha256", "rendered_variant_sha256"}

    def project(value):
        if isinstance(value, dict):
            return {key: project(child) for key, child in value.items() if key.casefold() not in volatile}
        return [project(child) for child in value] if isinstance(value, list) else value

    digest = hashlib.sha256(json.dumps({"family": style["family"], "study_archetype": style["study_archetype"],
                                       "target_venue": style["target_venue"], "evidence_mode": options["non_experiment_evidence_mode"],
                                       "spec": spec.as_dict()}, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for relative in input_relatives(spec.node_id):
        path = root / relative
        if path.is_file():
            raw = path.read_bytes()
            if path.suffix == ".json":
                raw = json.dumps(project(json.loads(raw)), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            digest.update(relative.encode("utf-8"))
            digest.update(raw)
    return digest.hexdigest()


def _call_fixture(original: Path, root: Path, skill: Path, spec) -> tuple[dict, dict, dict]:
    artifact = original / spec.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(("\n".join(spec.required_headings) + "\n" + "Finite audit evidence only. " * 20).encode("utf-8"))
    session, provider, model = "original-model-session", "fixture-provider", "fixture-model"
    raw_call = {"schema": 1, "skill": spec.skill, "status": "completed", "session_id": session,
                "project_path": str(original), "policy_loaded": True, "skill_source": str(skill),
                "skill_sha256": _sha(skill.read_bytes()), "skill_bytes": len(skill.read_bytes()),
                "model_provider": provider, "model_name": model, "output_sha256": "c" * 64}
    relative = ".merak/skill-invocations/source_domain-validation.json"
    raw = _write(original / relative, raw_call)
    for path in (root / relative, root / ".merak/snapshot-source-traces/specialist-invocations/source_domain-validation.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    invocation = {**raw_call, "run_id": RUN_ID, "role": "profile_specialist", "execution_kind": "model_owned", "execution_verified": True}
    trace = {"schema": 2, "run_id": RUN_ID, "project_path": str(original), "stages": {"results": {"invocations": [invocation]}}}
    entry = {**spec.as_dict(), "run_id": RUN_ID, "status": "completed", "session_id": session,
             "model_provider": provider, "model_name": model, "completed_at": 100,
             "artifact_sha256": _sha(artifact.read_bytes()), "invocation_trace": str(original / relative)}
    return entry, trace, raw_call


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    original, root = tmp_path / "original", tmp_path / "copy"
    _inputs(original)
    style = {"schema_version": 2, "family": "machine_learning", "study_archetype": "algorithm_benchmark", "target_venue": "ICLR"}
    _write(original / "paper/PUBLICATION_STYLE.json", style)
    options = {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}
    spec = next(item for item in selected_specialists(style["family"], style["study_archetype"]) if item.id == "domain-validation")
    skill = tmp_path / "repository/merak-skills/domain-validation/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(b"---\nname: domain-validation\n---\nFinite full skill policy fixture.\n")
    monkeypatch.setattr(service, "REPOSITORY", tmp_path / "repository")
    entry, trace, raw_call = _call_fixture(original, root, skill, spec)
    entry["input_digest"] = _old_digest(original, style, spec, options)
    other = {"id": "unchanged-other", "status": "completed", "literal_evidence": "preserve exactly"}
    profile = {key: style[key] for key in ("family", "study_archetype", "target_venue")}
    profile["evidence_mode"] = "synthetic_preview"
    plan = {"schema": 1, "run_id": RUN_ID, "profile": profile, "subnodes": [other, entry]}
    source_run = {"schema": 1, "run_id": RUN_ID, "status": "cancelled", "config": {"direction": "Finite source direction", "options": options}}
    for suffix, value in (("specialists", plan), ("run", source_run), ("skills", trace)):
        relative = f".merak/runs/{RUN_ID}" + (".json" if suffix == "run" else f".{suffix}.json")
        raw = _write(original / relative, value)
        _write(root / f".merak/snapshot-source-traces/{RUN_ID}.{suffix}.original.json", value)
        assert raw == (root / f".merak/snapshot-source-traces/{RUN_ID}.{suffix}.original.json").read_bytes()
    for path in original.rglob("*"):
        if path.is_file() and not path.relative_to(original).parts[0] == ".merak":
            target = root / path.relative_to(original)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    payload = _read(planned)
    for row in payload["figures"][4:]:
        row["metadata"]["paper_selected"] = False
    _write(planned, payload)
    current = copy.deepcopy(plan)
    current["subnodes"][1] = {**spec.as_dict(), "run_id": RUN_ID, "status": "pending",
                             "input_digest": specialist_input_digest(root, style, spec, options)}
    _write(root / f".merak/runs/{RUN_ID}.specialists.json", current)
    _write(root / f".merak/runs/{RUN_ID}.json", {**source_run, "status": "incomplete"})
    _write(root / f".merak/runs/{RUN_ID}.skills.json", {**trace, "project_path": str(root)})
    return {"original": original, "root": root, "spec": spec, "source_entry": entry, "style": style,
            "options": options, "raw_call": raw_call}


def _prepare(evidence):
    return service.prepare_same_science_specialist_reuse(evidence["root"], evidence["original"], RUN_ID)


def test_identical_current_science_reuses_verified_old_audit_without_any_persistence(evidence):
    before = {key: _files(evidence[key]) for key in ("root", "original")}
    result, proof = _prepare(evidence)
    row = next(item for item in result["subnodes"] if item["id"] == "domain-validation")
    current = _read(evidence["root"] / f".merak/runs/{RUN_ID}.specialists.json")
    assert row["status"] == "reused" and row["session_id"] == ""
    assert row["reused_model_session_id"] == evidence["source_entry"]["session_id"]
    assert row["reused_from_run"] == RUN_ID and Path(row["reused_invocation_trace"]).is_relative_to(evidence["root"])
    assert result["subnodes"][0] == current["subnodes"][0]
    assert proof["original_legacy_input_digest"] == evidence["source_entry"]["input_digest"]
    assert proof["current_input_digest"] == proof["source_canonical_input_digest"] != proof["original_legacy_input_digest"]
    assert proof["canonical_input_bytes_equal"] is True and proof["no_new_model_execution"] is True
    assert proof["scientific_inputs_rewritten"] is False and proof["raw_invocation_records_rewritten"] is False
    assert before == {key: _files(evidence[key]) for key in ("root", "original")}


def test_pending_old_projection_is_recomputed_not_treated_as_completed_execution_proof(evidence):
    path = evidence["root"] / f".merak/runs/{RUN_ID}.specialists.json"
    payload = _read(path)
    payload["subnodes"][1]["input_digest"] = "d" * 64
    _write(path, payload)
    before = _files(evidence["root"])
    result, proof = _prepare(evidence)
    row = next(item for item in result["subnodes"] if item["id"] == "domain-validation")
    assert row["status"] == "reused" and row["input_digest"] == proof["current_input_digest"]
    assert proof["pending_prior_input_digest"] == "d" * 64
    assert proof["source_legacy_digest_verified"] is True and proof["no_new_model_execution"] is True
    assert _files(evidence["root"]) == before


@pytest.mark.parametrize("defect", ["claim", "members", "declared_source_hash", "data", "source", "missing_input", "style", "options", "plan_members"])
def test_changed_science_or_owner_identity_rejects_reuse_without_writes(evidence, defect):
    root = evidence["root"]
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    if defect in {"members", "declared_source_hash"}:
        payload = _read(planned)
        if defect == "members":
            payload["figures"].pop()
        else:
            payload["figures"][0]["source_sha256"] = "0" * 64
        _write(planned, payload)
    elif defect in {"data", "source"}:
        relative = "experiments/results/simulated/result_0.csv" if defect == "data" else "figures/simulated/result_0.py"
        (root / relative).write_bytes(b"Changed after original audit")
    elif defect == "missing_input":
        (root / "literature/survey.md").unlink()
    else:
        relative = {"claim": "ideas/SELECTED_IDEA.json", "style": "paper/PUBLICATION_STYLE.json",
                    "options": f".merak/runs/{RUN_ID}.json", "plan_members": f".merak/runs/{RUN_ID}.specialists.json"}[defect]
        path, payload = root / relative, _read(root / relative)
        if defect == "claim":
            payload["claims"][0]["statement"] = "A different claim"
        elif defect == "style":
            payload["target_venue"] = "Different venue"
        elif defect == "options":
            payload["config"]["options"]["run_experiment"] = True
        else:
            payload["subnodes"].append({"id": "foreign-specialist"})
        _write(path, payload)
    before = _files(root)
    with pytest.raises(ValueError):
        _prepare(evidence)
    assert _files(root) == before


@pytest.mark.parametrize("defect", ["status", "policy", "session", "skill_hash", "skill_bytes", "stage_empty", "stage_missing", "artifact", "source_digest", "raw_copy"])
def test_original_model_evidence_must_be_authentic_and_complete(evidence, defect):
    root, original = evidence["root"], evidence["original"]
    if defect in {"status", "policy", "session", "skill_hash", "skill_bytes"}:
        call = dict(evidence["raw_call"])
        key, value = {"status": ("status", "failed"), "policy": ("policy_loaded", False),
                      "session": ("session_id", "foreign-session"), "skill_hash": ("skill_sha256", "0" * 64),
                      "skill_bytes": ("skill_bytes", 1)}[defect]
        call[key] = value
        relative = ".merak/skill-invocations/source_domain-validation.json"
        _write(original / relative, call)
        _write(root / relative, call)
        _write(root / ".merak/snapshot-source-traces/specialist-invocations/source_domain-validation.json", call)
    elif defect in {"stage_empty", "stage_missing"}:
        path = original / f".merak/runs/{RUN_ID}.skills.json"
        payload = _read(path)
        if defect == "stage_empty":
            payload["stages"]["results"] = {}
        else:
            payload["stages"].pop("results")
        _write(path, payload)
        _write(root / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json", payload)
        _write(root / f".merak/runs/{RUN_ID}.skills.json", {**payload, "project_path": str(root)})
    elif defect == "source_digest":
        path = original / f".merak/runs/{RUN_ID}.specialists.json"
        payload = _read(path)
        payload["subnodes"][1]["input_digest"] = "0" * 64
        _write(path, payload)
        _write(root / f".merak/snapshot-source-traces/{RUN_ID}.specialists.original.json", payload)
    elif defect == "raw_copy":
        (root / ".merak/skill-invocations/source_domain-validation.json").write_bytes(b"Different raw model record")
    else:
        (root / evidence["spec"].artifact).write_bytes(b"Changed audit artifact")
    before = _files(root)
    with pytest.raises(ValueError):
        _prepare(evidence)
    assert _files(root) == before
