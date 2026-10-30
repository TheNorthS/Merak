from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path

import pytest

from server.services.execution_provenance import execution_provenance_service
from server.services.paper_compiler import paper_compiler
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
)
from server.tests._scientific_slide_fixture import write_current_slide_bundle
from server.services.workflow_inputs import snapshot_paths, workflow_input_service
from server.services.workflow_readiness import (
    READINESS_SCHEMA_VERSION,
    SUBMISSION_PHASES,
    workflow_readiness_service,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun
from server.workflows.run_state import RunState
from server.workflows.review_audit import (
    AUDIT_LAYER_SKILLS,
    AuditChain,
    AuditResult,
    Verdict,
    review_source_bundle,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _state(evidence_mode: str, phase_ids: tuple[str, ...] = SUBMISSION_PHASES) -> dict:
    return {
        "run_id": "readiness-run",
        "config": {
            "assurance": "submission",
            "options": {
                "run_experiment": evidence_mode == "executed",
                "non_experiment_evidence_mode": evidence_mode,
            },
        },
        "phases": {
            phase_id: {"id": phase_id, "status": "accepted"}
            for phase_id in phase_ids
        },
    }


def _artifacts(
    root: Path,
    evidence_mode: str,
    submission_eligible: bool,
    publication_ready: bool,
    audit_verdict: str,
    *,
    run_id: str = "readiness-run",
    executor_model: str = "executor-model",
    reviewer_model: str = "independent-reviewer-model",
) -> None:
    _write_json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json", {
        "evidence_mode": evidence_mode,
        "submission_eligible": submission_eligible,
    })
    _write_json(root / "figures" / "FIGURE_MANIFEST.json", {
        "schema": 1,
        "figures": [],
    })
    paper = root / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nSubmission candidate.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    _write_json(root / "paper" / "PAPER_BUILD.json", {
        "evidence_mode": evidence_mode,
        "submission_eligible": submission_eligible,
    })
    pdf = paper / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\nnot-empty\n")
    assert paper_compiler.refresh_build_record(
        paper,
        "PAPER_BUILD.json",
        "main.pdf",
        pages=1,
    ) is True

    review_hash, review_sources = review_source_bundle(root)
    original_snapshot = paper / "main_round0_original.pdf"
    final_snapshot = paper / "main_round1.pdf"
    original_snapshot.write_bytes(pdf.read_bytes())
    final_snapshot.write_bytes(pdf.read_bytes())
    layout_report = root / "review-stage" / "pdf-layout" / "main_round1.json"
    _write_json(layout_report, {
        "schema": 1,
        "pdf_path": str(final_snapshot),
        "page_count": 1,
        "renderer": "test-renderer",
        "pages": [{"page": 1, "possible_layout_findings": []}],
    })
    visual_review = {
        "pdf_path": "paper/main_round0_original.pdf",
        "figure_quality": "Figures are legible.",
        "caption_alignment": "Captions align with their floats.",
        "page_layout": "No clipping or overlap was observed.",
        "table_formatting": "Tables are consistently aligned.",
        "visual_consistency": "Typography and encodings are consistent.",
    }
    _write_json(root / "review-stage" / "REVIEW_STATE.json", {
        "managed_by": "cross_model_review_loop",
        "run_id": run_id,
        "evidence_mode": evidence_mode,
        "publication_ready": publication_ready,
        "policy_loaded": True,
        "source_bundle_sha256": review_hash,
        "sources": [path.relative_to(root).as_posix() for path in review_sources],
        "executor_model": executor_model,
        "reviewer_model": reviewer_model,
        "reviewer_session_ids": ["review-session"],
        "executor_session_ids": ["executor-session"],
        "is_complete": True,
        "threshold_met": True,
        "bounded_complete": True,
        "current_round": 1,
        "max_rounds": 1,
        "fallback_reason": "",
        "final_score": 8.0,
        "final_verdict": "ready",
        "rounds": [{
            "round": 1,
            "score": 8.0,
            "verdict": "ready",
            "pdf_snapshot": "paper/main_round0_original.pdf",
            "visual_review": visual_review,
        }],
        "pdf_snapshots": [
            {
                "round": 0,
                "snapshot_path": "paper/main_round0_original.pdf",
                "pdf_sha256": hashlib.sha256(
                    original_snapshot.read_bytes()
                ).hexdigest(),
                "source_bundle_sha256": review_hash,
                "layout_report_path": "review-stage/pdf-layout/main_round1.json",
            },
            {
                "round": 1,
                "snapshot_path": "paper/main_round1.pdf",
                "pdf_sha256": hashlib.sha256(
                    final_snapshot.read_bytes()
                ).hexdigest(),
                "source_bundle_sha256": review_hash,
                "layout_report_path": "review-stage/pdf-layout/main_round1.json",
            },
        ],
    })
    audit_entries = [
        AuditResult(
            layer=number,
            layer_name=f"Layer {number}",
            verdict=Verdict(audit_verdict),
            summary="audited",
            details="inspected evidence",
            evidence=["paper/main.tex"],
            method="model",
            policy_loaded=True,
            session_id=f"audit-session-{number}",
            skill_name=AUDIT_LAYER_SKILLS[number],
            model_name=reviewer_model,
        )
        for number in range(1, 6)
    ]
    AuditChain()._save_results(
        audit_entries,
        str(root),
        evidence_mode=evidence_mode,
        run_id=run_id,
    )


def _record_runtime_metric(root: Path) -> None:
    config = root / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("experiment:\n  metric: accuracy\n", encoding="utf-8")
    metric = root / "experiments" / "results" / "main_metrics.csv"
    metric.parent.mkdir(parents=True, exist_ok=True)
    metric.write_text(
        "status,method,seed,split,metric,value,ci95_low,ci95_high\n"
        "completed,Proposed,42,test,accuracy,0.81,0.79,0.83\n",
        encoding="utf-8",
    )
    now = time.time()
    execution_provenance_service.record(
        root,
        session_id="runtime-evidence-session",
        tool="Bash",
        arguments={
            "command": "python experiments/src/train.py --config experiments/configs/main.yaml",
            "cwd": str(root),
        },
        success=True,
        started_at=now - 1.0,
        finished_at=now,
        output="experiment completed",
    )


def _simulation_package(root: Path, *, schema: int = SIMULATION_MANIFEST_SCHEMA) -> Path:
    """Write finite current data; only the negative case declares retired schema."""
    manifest = write_current_slide_bundle(root)["simulation_manifest"]
    if schema != SIMULATION_MANIFEST_SCHEMA:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema"] = schema
        payload["data_files"] = payload["data_files"][:7]
        _write_json(manifest, payload)
    return manifest


def test_synthetic_preview_is_complete_and_keeps_distinct_delivery_class(tmp_path: Path) -> None:
    manifest = _simulation_package(tmp_path)
    _artifacts(tmp_path, "synthetic_preview", False, False, "WARN")
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    report = workflow_readiness_service.assess(
        tmp_path, _state("synthetic_preview")
    )

    assert report["execution_completed"] is True
    assert report["submission_ready"] is False
    assert report["completion_class"] == "synthetic_preview_ready"
    assert report["schema"] == READINESS_SCHEMA_VERSION
    assert len(report["readiness_input_sha256"]) == 64
    assert report["attestations"]["simulation"] == {
        "valid": True,
        "schema": SIMULATION_MANIFEST_SCHEMA,
        "primary_metric": "score",
        "metric_direction": "maximize",
        "bound_data_file_count": len(payload["data_files"]),
        "applicable": True,
    }
    persisted = json.loads(
        (tmp_path / ".merak" / "DELIVERY_STATUS.json").read_text(encoding="utf-8")
    )
    assert persisted["submission_ready"] is False


def test_legacy_simulation_manifest_cannot_be_marked_preview_ready(
    tmp_path: Path,
) -> None:
    _simulation_package(tmp_path, schema=4)
    _artifacts(tmp_path, "synthetic_preview", False, False, "WARN")

    report = workflow_readiness_service.assess(
        tmp_path,
        _state("synthetic_preview"),
        persist=False,
    )

    assert report["completion_class"] == "evidence_blocked"
    attestation = report["attestations"]["simulation"]
    assert attestation["applicable"] is True
    assert attestation["valid"] is False
    assert attestation["schema"] == 4
    assert attestation["bound_data_file_count"] == 7
    assert any(
        f"manifest schema is older than {SIMULATION_MANIFEST_SCHEMA}" in blocker
        for blocker in report["submission_blockers"]
    )


def test_empirical_submission_accepts_verified_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts(tmp_path, "executed", True, True, "PASS")
    monkeypatch.setattr(
        "server.services.workflow_readiness_assessment.scientific_evidence_service.validate_executed_metrics",
        lambda _root: (True, [], {"metric_count": 4, "execution_events": 1}),
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True
    assert report["completion_class"] == "submission_ready"
    assert report["submission_blockers"] == []


def test_empirical_submission_keeps_warn_audits_as_advisories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts(tmp_path, "executed", True, True, "WARN")
    monkeypatch.setattr(
        "server.services.workflow_readiness_assessment.scientific_evidence_service.validate_executed_metrics",
        lambda _root: (True, [], {"metric_count": 4, "execution_events": 1}),
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True
    assert report["submission_blockers"] == []
    assert report["submission_advisories"]
    assert "WARN" in report["submission_advisories"][0]


def test_empirical_submission_uses_real_hash_linked_runtime_evidence(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "WARN")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True
    assert report["completion_class"] == "submission_ready"
    assert report["evidence_details"]["metric_count"] == 1
    assert report["evidence_details"]["execution_events"] == 1
    assert report["evidence_details"]["proven_sources"] == [
        "experiments/results/main_metrics.csv"
    ]


def test_existing_results_submission_uses_hash_verified_input_import(
    tmp_path: Path,
) -> None:
    metric = tmp_path / "experiments" / "results" / "imported_metrics.csv"
    metric.parent.mkdir(parents=True, exist_ok=True)
    metric.write_text(
        "status,method,seed,split,metric,value\n"
        "completed,Imported baseline,7,test,accuracy,0.76\n",
        encoding="utf-8",
    )
    baseline = workflow_input_service.capture(
        tmp_path,
        ["experiments/results/imported_metrics.csv"],
        run_id="imported-evidence-run",
    )
    manifest = execution_provenance_service.record_import(
        tmp_path,
        run_id="imported-evidence-run",
        evidence_mode="existing_results",
        input_baseline=baseline,
    )
    _artifacts(tmp_path, "existing_results", True, True, "WARN")

    report = workflow_readiness_service.assess(
        tmp_path, _state("existing_results"), persist=False
    )

    assert manifest["artifacts"]
    assert report["submission_ready"] is True
    assert report["evidence_details"]["execution_events"] == 0
    assert report["evidence_details"]["imported_sources"] == [
        "experiments/results/imported_metrics.csv"
    ]


def test_existing_results_import_is_invalidated_by_file_change(
    tmp_path: Path,
) -> None:
    metric = tmp_path / "experiments" / "results" / "imported_metrics.csv"
    metric.parent.mkdir(parents=True, exist_ok=True)
    metric.write_text(
        "status,method,metric,value\ncompleted,Imported,accuracy,0.76\n",
        encoding="utf-8",
    )
    baseline = workflow_input_service.capture(
        tmp_path,
        ["experiments/results/imported_metrics.csv"],
        run_id="stale-import-run",
    )
    execution_provenance_service.record_import(
        tmp_path,
        run_id="stale-import-run",
        evidence_mode="existing_results",
        input_baseline=baseline,
    )
    _artifacts(tmp_path, "existing_results", True, True, "PASS")
    metric.write_text(
        "status,method,metric,value\ncompleted,Imported,accuracy,0.99\n",
        encoding="utf-8",
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("existing_results"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "hash-verified evidence import" in item
        for item in report["submission_blockers"]
    )


def test_submission_is_invalidated_when_reviewed_tex_changes(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    main = tmp_path / "paper" / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8") + "\n% unreviewed scientific edit\n",
        encoding="utf-8",
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "paper build is stale" in item
        for item in report["submission_blockers"]
    )
    assert any(
        "independent review is stale" in item
        for item in report["submission_blockers"]
    )


def test_submission_is_invalidated_when_audit_results_change(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    results_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    entries = json.loads(results_path.read_text(encoding="utf-8"))
    entries[0]["summary"] = "changed after attestation"
    results_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "AUDIT_RESULTS.json does not match" in item
        for item in report["submission_blockers"]
    )


def test_submission_is_invalidated_when_proof_audit_changes(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    proof_path = tmp_path / "paper" / "PROOF_AUDIT.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["summary"] = "changed after build attestation"
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "PROOF_AUDIT.json does not match" in item
        for item in report["submission_blockers"]
    )


def test_submission_requires_explicit_no_theorems_proof_verdict(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    (tmp_path / "paper" / "PROOF_AUDIT.json").unlink()

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "proof-checker artifact is missing" in item
        for item in report["submission_blockers"]
    )


def test_submission_allows_same_model_reviewer_with_isolated_session(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(
        tmp_path,
        "executed",
        True,
        True,
        "PASS",
        executor_model="shared-model",
        reviewer_model="shared-model",
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True, report["submission_blockers"]
    assert not report["submission_blockers"]


def test_submission_requires_compiled_pdf_visual_review_attestation(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    review_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["rounds"][-1].pop("visual_review")
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "visual/layout attestation" in item
        for item in report["submission_blockers"]
    )


def test_submission_requires_hash_bound_final_review_pdf_snapshot(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    (tmp_path / "paper" / "main_round1.pdf").write_bytes(
        b"%PDF-1.4\nchanged-after-review\n"
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "final PDF snapshot hash does not match" in item
        for item in report["submission_blockers"]
    )


def test_same_provider_with_different_models_can_certify_independently(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(
        tmp_path,
        "executed",
        True,
        True,
        "PASS",
        executor_model="openai/gpt-writer",
        reviewer_model="openai/gpt-reviewer",
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True


def test_submission_requires_audit_model_identity(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    audit_path = tmp_path / "audit-results" / "AUDIT_RESULTS.json"
    entries = json.loads(audit_path.read_text(encoding="utf-8"))
    entries[0].pop("model_name", None)
    audit_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    build_path = tmp_path / "audit-results" / "AUDIT_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["results_sha256"] = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    build_path.write_text(json.dumps(build, indent=2), encoding="utf-8")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "audit layer 1 has no model identity" in item
        for item in report["submission_blockers"]
    )


def test_submission_allows_same_model_audit_with_durable_sessions(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(
        tmp_path,
        "executed",
        True,
        True,
        "PASS",
        executor_model="shared-model",
        reviewer_model="shared-model",
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is True, report
    assert not report["submission_blockers"]


def test_submission_is_invalidated_when_figure_manifest_points_to_missing_asset(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(tmp_path, "executed", True, True, "PASS")
    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figures"] = [{
        "id": "main-result",
        "output_path": "figures/plots/main-result.png",
        "output_sha256": "0" * 64,
        "paper_ready": True,
        "metadata": {"evidence_status": "executed"},
    }]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = workflow_readiness_service.assess(
        tmp_path, _state("executed"), persist=False
    )

    assert report["submission_ready"] is False
    assert any(
        "scientific figure bundle" in item
        for item in report["submission_blockers"]
    )


def test_completed_submission_read_preserves_historical_acceptance_after_local_edit(
    tmp_path: Path,
) -> None:
    _record_runtime_metric(tmp_path)
    _artifacts(
        tmp_path,
        "executed",
        True,
        True,
        "PASS",
        run_id="rebuild-stale-submission",
    )
    engine = WorkflowEngine()
    run_id = "rebuild-stale-submission"
    options = {"run_experiment": True}
    nodes = engine._get_default_nodes()
    baseline = workflow_input_service.capture(tmp_path, [], run_id=run_id)
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        nodes=nodes,
        options=options,
        input_baseline=baseline,
    )
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill} for node in nodes],
        {
            "direction": "test",
            "assurance": "submission",
            "options": options,
        },
        input_baseline=baseline,
    )
    for node in nodes:
        state.set_status(node.id, "done")
        requirements = engine._gate_requirements_for_node(run, node.id)
        state.accept(
            node.id,
            f"accepted:{node.id}",
            "deterministic:test",
            details={
                "artifact_snapshot": snapshot_paths(
                    tmp_path,
                    requirements,
                    directory_exclusions=engine._artifact_directory_exclusions(
                        node.id
                    ),
                ),
                "input_baseline_snapshot_id": baseline["snapshot_id"],
                "risk_audit_bound": False,
            },
        )
    ready = workflow_readiness_service.assess(
        tmp_path,
        state.load(),
        persist=True,
    )
    assert ready["submission_ready"] is True
    assert state.complete(ready) is True
    historical = state.load()

    main = tmp_path / "paper" / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8") + "\n% changed after acceptance\n",
        encoding="utf-8",
    )

    refreshed = engine.get_persisted_run_state(str(tmp_path), run_id)

    assert refreshed is not None
    assert refreshed == historical
    assert refreshed["status"] == "completed"
    assert refreshed["submission_ready"] is True  # Historical delivery, not the new local revision.
    for phase_id in ("paper", "review", "audit", "compile", "ppt"):
        assert refreshed["phases"][phase_id]["status"] == "accepted"

    snapshot = engine.get_resumable_run_snapshot(str(tmp_path), run_id)
    assert snapshot is None
    listed = engine.list_persisted_runs(str(tmp_path))
    assert listed[0]["auto_rebuild_required"] is None


def test_empirical_submission_blocks_missing_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts(tmp_path, "existing_results", True, True, "PASS")
    monkeypatch.setattr(
        "server.services.workflow_readiness_assessment.scientific_evidence_service.validate_executed_metrics",
        lambda _root: (
            False,
            ["metric file is not hash-linked to an accepted run"],
            {"metric_count": 1, "execution_events": 0},
        ),
    )

    report = workflow_readiness_service.assess(
        tmp_path, _state("existing_results"), persist=False
    )

    assert report["submission_ready"] is False
    assert report["completion_class"] == "evidence_blocked"
    assert any("hash-linked" in item for item in report["submission_blockers"])


def test_partial_run_is_not_a_complete_manuscript(tmp_path: Path) -> None:
    report = workflow_readiness_service.assess(
        tmp_path,
        _state("design_only", phase_ids=("lit",)),
        persist=False,
    )

    assert report["execution_completed"] is True
    assert report["submission_ready"] is False
    assert report["completion_class"] == "partial_workflow_complete"
    assert "idea" in report["missing_submission_phases"]


def test_run_state_persists_separate_completion_fields(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "run-state-completion")
    state.start(
        [{"id": "lit", "name": "Literature", "skill": "/research-lit"}],
        {"direction": "test", "options": {}},
    )
    state.set_status("lit", "done", artifact="literature/survey.md")
    state.accept("lit", "verdict", "deterministic:test")

    assert state.complete({
        "execution_completed": True,
        "submission_ready": False,
        "completion_class": "partial_workflow_complete",
    }) is True

    persisted = state.load()
    assert persisted is not None
    assert persisted["status"] == "completed"
    assert persisted["execution_completed"] is True
    assert persisted["submission_ready"] is False
    assert persisted["completion_class"] == "partial_workflow_complete"


def test_completed_run_reads_never_migrate_legacy_readiness_or_changed_inputs(
    tmp_path: Path,
) -> None:
    _simulation_package(tmp_path)
    _artifacts(tmp_path, "synthetic_preview", False, False, "WARN")
    run_id = "legacy-readiness-refresh"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [
            {"id": phase_id, "name": phase_id, "skill": f"/{phase_id}"}
            for phase_id in SUBMISSION_PHASES
        ],
        {
            "assurance": "submission",
            "options": {
                "run_experiment": False,
                "non_experiment_evidence_mode": "synthetic_preview",
            },
        },
    )
    for phase_id in SUBMISSION_PHASES:
        state.set_status(phase_id, "done")
        state.accept(
            phase_id,
            f"{phase_id}:legacy-verdict",
            "deterministic:test",
        )
    assert state.complete({
        "schema": 1,
        "execution_completed": True,
        "submission_ready": False,
        "completion_class": "synthetic_preview_ready",
    }) is True
    before = state.load()
    assert before is not None
    original_finished_at = before["finished_at"]

    engine = WorkflowEngine()
    migrated = engine.get_persisted_run_state(str(tmp_path), run_id)

    assert migrated is not None
    assert migrated == before
    assert migrated["completion"]["schema"] == 1
    assert migrated["finished_at"] == original_finished_at

    _write_json(tmp_path / "paper" / "PAPER_BUILD.json", {
        "evidence_mode": "synthetic_preview",
        "submission_eligible": False,
        "revision": 2,
    })
    assert workflow_readiness_service.needs_refresh(tmp_path, migrated) is True

    refreshed = engine.get_persisted_run_state(str(tmp_path), run_id)
    assert refreshed is not None
    assert refreshed == before
