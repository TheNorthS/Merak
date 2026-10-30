"""Pure execution-proof regressions; selected producers never count as execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_execution_policy import FIGURE_RUNTIME_SERVICE
from server.services.skill_execution_trace import SkillExecutionTrace, trace_path
from server.services.skill_orchestrator import SkillPlan


RUN = "figure-proof"


def _assets(root: Path, *, model: bool = False) -> list[dict]:
    assets = [{"id": "method_architecture", "kind": "figure", "required": True,
               "producer_kind": "deterministic", "production_strategy": "deterministic_architecture",
               "composition_owner": "runtime", "recommended_skill": "figure-spec",
               "recommended_backend": "figurespec", "generation_policy": "generate",
               "figure_nature": "conceptual", "full_svg_authority": False}]
    if model:
        assets.append({"id": "illustration", "kind": "figure", "required": True,
                       "producer_kind": "model", "production_strategy": "model_generated_image",
                       "composition_owner": "model", "recommended_skill": "paper-illustration",
                       "recommended_backend": "nano_banana", "generation_policy": "generate",
                       "figure_nature": "naturalistic", "full_svg_authority": False})
    directory = root / "figures"
    directory.mkdir()
    (directory / "FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "publication_label_schema": 1, "production_policy_schema": 1, "figures": assets,
    }), encoding="utf-8")
    entries = []
    for asset in assets:
        source, output, preview = (directory / f"{asset['id']}.{suffix}" for suffix in ("svg", "pdf", "png"))
        source.write_bytes(b"source-bound fixture")
        output.write_bytes(b"rendered fixture")
        preview.write_bytes(b"preview fixture")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({
            "id": asset["id"], "paper_ready": True,
            "source_path": source.relative_to(root).as_posix(), "source_sha256": digest(source),
            "output_path": output.relative_to(root).as_posix(), "output_sha256": digest(output),
            "metadata": {**asset, "semantic_key": asset["id"], "paper_selected": True,
                         "skill_session_id": "illustration-session" if asset["producer_kind"] == "model" else "",
                         "model_authored": asset["producer_kind"] == "model",
                         "generator_skill": asset["recommended_skill"], "skill_invocation_verified": True,
                         "rendered_variants": {"svg": source.relative_to(root).as_posix(),
                                               "pdf": output.relative_to(root).as_posix(), "png": preview.relative_to(root).as_posix()},
                         "rendered_variant_sha256": {"svg": digest(source), "pdf": digest(output), "png": digest(preview)}}})
    (directory / "FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": entries}), encoding="utf-8")
    return assets


@pytest.fixture
def proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(figure_artifact_registry, "scientific_quality_issues", lambda _path: [])
    monkeypatch.setattr(figure_artifact_registry, "scientific_alignment_issues", lambda _path: [])
    policy = tmp_path / "fixture-skill-policy.md"
    policy.write_text("Complete fixture policy for a verified isolated model session.", encoding="utf-8")
    registry = SimpleNamespace(total_skills=2, get_skill=lambda _name: SimpleNamespace(file_path=str(policy)))
    return SkillExecutionTrace(registry), tmp_path


def _plan(*, model: bool = False) -> SkillPlan:
    return SkillPlan(node_id="figure", primary="paper-illustration" if model else "figure-spec",
                     execution_kind="hybrid" if model else "runtime_owned", runtime_service=FIGURE_RUNTIME_SERVICE,
                     policy_required=model, model_execution_mode="any_component" if model else "primary")


def _complete_runtime(trace: SkillExecutionTrace, root: Path, service: str = FIGURE_RUNTIME_SERVICE) -> None:
    trace.mark_runtime_execution(str(root), RUN, "figure", service, "completed", operation_id="render-and-gate")


def _update_trace(root: Path, edit) -> None:
    path = trace_path(str(root), RUN)
    payload = json.loads(path.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_deterministic_current_run_is_runtime_only_without_fake_model(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["accepted"] is True
    assert gate["requires_model"] is False
    assert gate["model_execution_verified"] is False
    assert gate["runtime_execution_verified"] is True


@pytest.mark.parametrize("fault", ["missing", "wrong-run", "wrong-stage", "wrong-project", "wrong-schema"])
def test_missing_or_wrong_identity_never_satisfies_execution(proof, fault: str) -> None:
    trace, root = proof
    _assets(root)
    if fault != "missing":
        trace.record(str(root), RUN, _plan())
        _complete_runtime(trace, root)
        edits = {"wrong-run": lambda value: value.update(run_id="another-run"),
                 "wrong-stage": lambda value: value["stages"]["figure"].update(node_id="idea"),
                 "wrong-project": lambda value: value.update(project_path=str(root / "another-project")),
                 "wrong-schema": lambda value: value.update(schema=1)}
        _update_trace(root, edits[fault])
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is False


def test_wrong_runtime_cannot_rewrite_the_declared_service_or_pass(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root, "unrelated_service")
    payload = json.loads(trace_path(str(root), RUN).read_text(encoding="utf-8"))
    assert payload["stages"]["figure"]["runtime_service"] == FIGURE_RUNTIME_SERVICE
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is False


def test_new_wrong_runtime_cannot_borrow_a_previous_expected_completion(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    _complete_runtime(trace, root, "unrelated_service")
    assert trace.execution_gate(str(root), RUN, "figure")["runtime_execution_verified"] is False


def test_completed_runtime_is_execution_not_acceptance_of_a_rejected_asset(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    trace.mark_runtime_execution(str(root), RUN, "figure", FIGURE_RUNTIME_SERVICE, "completed",
                                 operation_id="rejected-gate", output=json.dumps({"accepted": False}))
    manifest_path = root / "figures/FIGURE_MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["figures"][0]["paper_ready"] = False
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["runtime_execution_verified"] is True
    assert gate["accepted"] is False


def test_record_never_relabels_a_foreign_run_trace(proof) -> None:
    trace, root = proof
    trace.record(str(root), RUN, _plan())
    _update_trace(root, lambda payload: payload.update(run_id="foreign-run"))
    with pytest.raises(RuntimeError, match="identity or schema"):
        trace.record(str(root), RUN, _plan())


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_latest_incomplete_runtime_cannot_borrow_previous_completion(proof, status: str) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    trace.mark_runtime_execution(str(root), RUN, "figure", FIGURE_RUNTIME_SERVICE, status, operation_id="new-operation")
    assert trace.execution_gate(str(root), RUN, "figure")["runtime_execution_verified"] is False


def test_wrong_run_runtime_invocation_is_not_current_run_evidence(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    _update_trace(root, lambda payload: payload["stages"]["figure"]["runtime_invocations"][-1].update(run_id="other-run"))
    assert trace.execution_gate(str(root), RUN, "figure")["runtime_execution_verified"] is False


def test_legacy_same_run_fields_preserve_genuine_upstream_execution(proof) -> None:
    trace, root = proof
    plan = SkillPlan(node_id="compile", primary="paper-compile", execution_kind="runtime_owned",
                     runtime_service="paper_compiler", policy_required=False)
    trace.record(str(root), RUN, plan)
    trace.mark_runtime_execution(str(root), RUN, "compile", "paper_compiler", "completed", operation_id="compile")
    def legacy(payload):
        payload.pop("project_path")
        payload["stages"]["compile"].pop("run_id")
        payload["stages"]["compile"]["runtime_invocations"][0].pop("run_id")
    _update_trace(root, legacy)
    assert trace.execution_gate(str(root), RUN, "compile")["accepted"] is True


def test_old_hybrid_trace_must_be_reselected_not_silently_promoted(proof) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan(model=True))
    _complete_runtime(trace, root)
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["accepted"] is False
    assert any("differs from current canonical" in issue for issue in gate["issues"])
    trace.record(str(root), RUN, _plan())
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is True


@pytest.mark.parametrize("fault", ["stale-source", "stale-output", "missing-variant", "rejected", "producer-change"])
def test_stale_or_rejected_assets_do_not_count_as_runtime_success(proof, fault: str) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    manifest_path = root / "figures/FIGURE_MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = payload["figures"][0]
    if fault in {"stale-source", "stale-output"}:
        key = "source_path" if fault == "stale-source" else "output_path"
        (root / entry[key]).write_bytes(b"changed without acceptance")
    elif fault == "missing-variant":
        entry["metadata"]["rendered_variant_sha256"].pop("png")
    elif fault == "rejected":
        entry["paper_ready"] = False
    else:
        entry["metadata"]["producer_kind"] = "model"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is False


@pytest.mark.parametrize("fault", ["missing", "wrong-skill", "wrong-session", "wrong-role", "wrong-run", "matching"])
def test_model_asset_requires_its_actual_declared_skill_and_accepted_session(proof, fault: str) -> None:
    trace, root = proof
    _assets(root, model=True)
    trace.record(str(root), RUN, _plan(model=True))
    _complete_runtime(trace, root)
    if fault != "missing":
        trace.mark_execution(str(root), RUN, "figure", "research-lit" if fault == "wrong-skill" else "paper-illustration",
                             "completed", role="validator" if fault == "wrong-role" else "delegate",
                             session_id="other-session" if fault == "wrong-session" else "illustration-session",
                             policy_loaded=True, execution_kind="model_owned")
        if fault == "wrong-run":
            _update_trace(root, lambda value: value["stages"]["figure"]["invocations"][-1].update(run_id="other-run"))
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["accepted"] is (fault == "matching")
    assert gate["model_requirement_verified"] is (fault == "matching")


def test_scientific_rejection_remains_blocking_in_execution_gate(proof, monkeypatch: pytest.MonkeyPatch) -> None:
    trace, root = proof
    _assets(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    monkeypatch.setattr(figure_artifact_registry, "scientific_quality_issues", lambda _path: ["current pixel review rejected"])
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is False


def test_model_session_that_later_failed_cannot_borrow_earlier_success(proof) -> None:
    trace, root = proof
    _assets(root, model=True)
    trace.record(str(root), RUN, _plan(model=True))
    _complete_runtime(trace, root)
    for status in ("completed", "failed"):
        trace.mark_execution(str(root), RUN, "figure", "paper-illustration", status, role="delegate",
                             session_id="illustration-session", policy_loaded=True, execution_kind="model_owned")
    assert trace.execution_gate(str(root), RUN, "figure")["model_requirement_verified"] is False


def _add_optional_plot(root: Path, *, required: bool = False, present: bool = False) -> None:
    asset = {"id": "optional_result", "kind": "figure", "required": required,
             "producer_kind": "deterministic", "production_strategy": "deterministic_plot",
             "composition_owner": "runtime", "recommended_skill": "paper-figure",
             "recommended_backend": "matplotlib", "generation_policy": "generate",
             "figure_nature": "quantitative", "full_svg_authority": False}
    specs_path = root / "figures/FIGURE_SPECS.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    specs["figures"].append(asset)
    specs_path.write_text(json.dumps(specs), encoding="utf-8")
    if not present:
        return
    source, output, preview = (root / "figures" / f"optional_result.{suffix}" for suffix in ("py", "pdf", "png"))
    for path in (source, output, preview):
        path.write_bytes(b"current optional asset fixture")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = root / "figures/FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figures"].append({
        "id": asset["id"], "paper_ready": True,
        "source_path": source.relative_to(root).as_posix(), "source_sha256": digest(source),
        "output_path": output.relative_to(root).as_posix(), "output_sha256": digest(output),
        "metadata": {**asset, "paper_selected": True,
                     "rendered_variants": {"pdf": output.relative_to(root).as_posix(), "png": preview.relative_to(root).as_posix()},
                     "rendered_variant_sha256": {"pdf": digest(output), "png": digest(preview)}}})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_absent_optional_deterministic_plot_does_not_block_required_figures(proof) -> None:
    trace, root = proof
    _assets(root)
    _add_optional_plot(root)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    assert trace.execution_gate(str(root), RUN, "figure")["accepted"] is True


def test_missing_required_deterministic_plot_still_blocks(proof) -> None:
    trace, root = proof
    _assets(root)
    _add_optional_plot(root, required=True)
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["accepted"] is False
    assert any("optional_result" in issue for issue in gate["issues"])


def test_visible_optional_plot_stale_hash_still_blocks(proof) -> None:
    trace, root = proof
    _assets(root)
    _add_optional_plot(root, present=True)
    (root / "figures/optional_result.pdf").write_bytes(b"changed without acceptance")
    trace.record(str(root), RUN, _plan())
    _complete_runtime(trace, root)
    gate = trace.execution_gate(str(root), RUN, "figure")
    assert gate["accepted"] is False
    assert any("optional_result" in issue and "stale" in issue for issue in gate["issues"])
