"""Pure fixture regressions for stage ownership and runtime finalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.contracts.implementation_evidence import parse_evidence_patch_document
from server.services.experiment_implementation_build import experiment_implementation_build_service
from server.services.method_contract_persistence import apply_implementation_evidence_patches
from server.tests.test_experiment_implementation_build import (
    _seed_contracts,
    _write_complete_pipeline,
    _write_json,
)
from server.workflows.implementation_execution_contracts import ImplementationContext
from server.workflows.implementation_reconciliation import (
    capture_protected_inputs,
    prepare_stage,
    reconcile_attempt,
)
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.implementation_stage_progress import (
    StageProgressSnapshot, stage_stop_reason,
)


DIRECTION = "classification research"
SERVICE = experiment_implementation_build_service


def _context(root: Path) -> ImplementationContext:
    _seed_contracts(root)
    _write_complete_pipeline(root)
    stages = SERVICE.stages(root, DIRECTION)
    return ImplementationContext(
        None, WorkflowRun(id="local-contract-fixture", project_path=str(root)),
        DIRECTION, WorkflowNode(id="exp-design", name="Experiment design", skill="/experiment-plan"), stages, SERVICE,
    )


def _accept_owners(context: ImplementationContext) -> None:
    for stage in context.stages[:-1]:
        report = SERVICE.validate_stage(context.root, stage.id, DIRECTION)
        assert report["passed"], report
        SERVICE.record_stage(
            context.root, stage.id, report, DIRECTION,
            attempts=1, session_summaries=["Original model-owned attempt"],
        )


def _planned_method(root: Path) -> tuple[Path, dict]:
    path = root / "experiments/METHOD_CONTRACT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "planned"
    payload["implementation_checks"] = []
    payload["mechanism_coverage"][0].update(
        implementation_check_ids=[], status="staged_pending", evidence_plan="Frozen plan",
    )
    _write_json(path, payload)
    return path, payload


def _patch(root: Path, mechanism_ids: list[str]) -> dict:
    payload = json.loads((root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json").read_text(encoding="utf-8"))
    payload["checks"][0]["idea_mechanism_ids"] = mechanism_ids
    return payload


def test_explicit_mechanism_links_are_merged_without_lifecycle_or_design_changes(tmp_path: Path) -> None:
    _context(tmp_path)
    method_path, before = _planned_method(tmp_path)
    patches = parse_evidence_patch_document(_patch(tmp_path, ["M1"]))

    assert apply_implementation_evidence_patches(method_path, patches)

    after = json.loads(method_path.read_text(encoding="utf-8"))
    assert after["status"] == "planned"
    assert after["mechanism_coverage"][0]["implementation_check_ids"] == ["I1"]
    assert after["mechanism_coverage"][0]["evidence_plan"] == "Frozen plan"
    for field in ("scientific_scene", "claim_evidence_plan", "evaluation_contract", "idea_contract_sha256"):
        assert after[field] == before[field]


def test_unknown_mechanism_is_rejected_before_contract_write(tmp_path: Path) -> None:
    _context(tmp_path)
    method_path, _ = _planned_method(tmp_path)
    before = method_path.read_bytes()

    with pytest.raises(ValueError, match="unknown idea mechanism.*M999"):
        apply_implementation_evidence_patches(
            method_path, parse_evidence_patch_document(_patch(tmp_path, ["M999"])),
        )

    assert method_path.read_bytes() == before


def test_check_names_do_not_imply_mechanism_coverage(tmp_path: Path) -> None:
    _context(tmp_path)
    method_path, _ = _planned_method(tmp_path)
    patch = _patch(tmp_path, [])
    patch["checks"][0]["check_id"] = "M1-is-implemented"

    apply_implementation_evidence_patches(method_path, parse_evidence_patch_document(patch))

    after = json.loads(method_path.read_text(encoding="utf-8"))
    assert after["mechanism_coverage"][0]["implementation_check_ids"] == []
    report = SERVICE.validate_stage(tmp_path, "integration", DIRECTION)
    assert not report["passed"]
    assert any("no implementation_check_ids" in issue for issue in report["issues"])


@pytest.mark.parametrize("mechanism_ids", ["M1", [""], ["M1", " M1 "]])
def test_mechanism_link_contract_rejects_invalid_shapes(tmp_path: Path, mechanism_ids) -> None:
    _context(tmp_path)
    patch = _patch(tmp_path, [])
    patch["checks"][0]["idea_mechanism_ids"] = mechanism_ids

    with pytest.raises(ValueError, match="idea_mechanism_ids"):
        parse_evidence_patch_document(patch)


def test_planned_candidate_is_deeply_audited_before_any_finalization(tmp_path: Path) -> None:
    _context(tmp_path)
    method_path = tmp_path / "experiments/METHOD_CONTRACT.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["status"] = "planned"
    _write_json(method_path, method)
    (tmp_path / "experiments/src/train.py").write_text(
        "def main():\n    return 1\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )

    report = SERVICE.validate_stage(tmp_path, "integration", DIRECTION)

    assert not report["passed"]
    assert any("Implemented ML method does not" in issue for issue in report["issues"])
    assert "experiments/src/train.py" in report["repair_targets"]
    assert json.loads(method_path.read_text(encoding="utf-8"))["status"] == "planned"


def test_integration_input_changes_require_owner_reconciliation(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _accept_owners(context)
    method_path, planned = _planned_method(tmp_path)
    state = prepare_stage(context, context.stages[-1])
    protection = capture_protected_inputs(context, state)
    before_source = {
        path: path.read_bytes() for path in (tmp_path / "experiments/src").glob("*.py")
    }
    _write_json(tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json", _patch(tmp_path, ["M1"]))
    config = tmp_path / "experiments/configs/main.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "evaluation:\n  bootstrap_samples: 2000\n", encoding="utf-8")

    report = reconcile_attempt(context, state, protection)

    assert not report["passed"]
    assert any("owning stage must reconcile" in issue for issue in report["issues"])
    method = json.loads(method_path.read_text(encoding="utf-8"))
    assert method["status"] == "planned"
    assert method["scientific_scene"] == planned["scientific_scene"]
    for stage in context.stages[:-1]:
        assert not SERVICE.can_reuse(tmp_path, stage.id, DIRECTION)
    assert all(path.read_bytes() == content for path, content in before_source.items())
    SERVICE.record_stage(tmp_path, "integration", report, DIRECTION)
    assert SERVICE.audit(tmp_path, DIRECTION)["blocking"]



def test_failed_integration_preserves_reusable_unchanged_owner_prefix(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _accept_owners(context)
    _planned_method(tmp_path)
    config = tmp_path / "experiments/configs/main.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "evaluation:\n  bootstrap_samples: 2000\n", encoding="utf-8")

    result = SERVICE.revalidate_existing_build(tmp_path, DIRECTION)

    assert not result["refreshed"] and not result["complete"]
    assert any("scientific input contract changed" in issue for issue in result["issues"])
    for stage in context.stages[:-1]:
        assert not SERVICE.can_reuse(tmp_path, stage.id, DIRECTION)
        assert SERVICE.load_build(tmp_path)["stages"][stage.id]["attempts"] == 1



def test_stage_cannot_write_a_future_owners_patch(tmp_path: Path) -> None:
    context = _context(tmp_path)
    state = prepare_stage(context, context.stages[2])
    protection = capture_protected_inputs(context, state)
    patch = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    patch.write_text('{"schema":1,"checks":[]}', encoding="utf-8")

    report = reconcile_attempt(context, state, protection)

    assert not report["passed"]
    assert report["ownership_violations"] == ["experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"]


def test_blocked_pipeline_diagnostics_route_only_to_named_stage_producers(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _accept_owners(context)
    _planned_method(tmp_path)

    report = SERVICE.audit(tmp_path, DIRECTION)

    assert report["blocking"]
    assert report["findings"]
    assert all(finding["category"] == "staged_implementation" for finding in report["findings"])
    assert "experiments/EXPERIMENT_PLAN.md" not in report["repair_scope"]["target_files"]
    assert "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json" in report["repair_scope"]["target_files"]
    assert report["findings"] == SERVICE.audit(tmp_path, DIRECTION)["findings"]


@pytest.mark.parametrize(("after_findings", "after_hash", "passed", "expected"), [
    ({"missing link"}, "same", False, "no_artifact_progress"),
    ({"missing link"}, "changed", False, "ineffective_content_change"),
    (set(), "same", True, ""),
    ({"new finding"}, "changed", False, ""),
    (set(), "changed", False, ""),
])
def test_no_progress_stops_prose_and_byte_churn_but_accepts_gate_progress(
    after_findings: set[str], after_hash: str, passed: bool, expected: str,
) -> None:
    before = StageProgressSnapshot(frozenset({"missing link"}), "same")
    after = StageProgressSnapshot(frozenset(after_findings), after_hash)

    assert stage_stop_reason(before, after, {"passed": passed}) == expected


@pytest.mark.asyncio
async def test_stage_does_not_repeat_a_prose_only_unsolved_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.workflows.implementation_model_invocation import StageModelInvocation
    from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator

    events: list[str] = []
    calls: list[int] = []

    class Host:
        async def _emit(self, _run, event: str, _data: dict) -> None:
            events.append(event)

    context = _context(tmp_path)
    context = ImplementationContext(
        Host(), context.run, context.direction, context.node, context.stages, context.service,
    )
    stage = context.stages[0]
    failed = {
        "stage_id": stage.id, "targets": list(stage.targets),
        "passed": False, "issues": ["data stage has no loading path"],
    }
    monkeypatch.setattr(SERVICE, "validate_stage", lambda *_args, **_kwargs: dict(failed))
    state = prepare_stage(context, stage)

    async def prose_only(invocation) -> str:
        calls.append(invocation.attempt)
        return "The implementation is done."

    monkeypatch.setattr(StageModelInvocation, "run", prose_only)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *_args, **_kwargs: None)
    coordinator = StagedImplementationCoordinator(context.host, context.run, DIRECTION)

    await coordinator._attempts(context, state)

    assert calls == [1]
    assert not state.report["passed"]
    assert "implementation_stage_no_progress" in events
    assert SERVICE.load_build(tmp_path)["stages"]["data"]["status"] == "needs_revision"


@pytest.mark.asyncio
async def test_stage_invocation_passes_exact_finding_authorized_write_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import server.agent.tools as agent_tools
    from server.workflows.implementation_model_invocation import StageModelInvocation

    context = _context(tmp_path)
    state = prepare_stage(context, context.stages[-1])
    state.effective_targets.append("experiments/src/train.py")
    captured: dict = {}

    class Host:
        async def _await_agent_with_activity_watchdog(self, *, task, **_kwargs):
            return await task

    context = ImplementationContext(
        Host(), context.run, context.direction, context.node, context.stages, context.service,
    )

    async def capture_invocation(_skill, _arguments, **kwargs) -> str:
        captured.update(kwargs)
        return "Bounded static authoring"

    monkeypatch.setattr(agent_tools, "invoke_skill", capture_invocation)

    await StageModelInvocation(context, state, 1)._invoke()

    assert captured["allowed_write_paths"] == state.effective_targets
    assert captured["allowed_write_paths"] is not state.effective_targets
    assert "METHOD_CONTRACT lifecycle state" in captured["invocation_contract"]
    assert captured["resume_input_fingerprint"] == context.service.input_hash(context.root, "integration", context.direction)
