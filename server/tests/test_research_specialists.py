from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from server.services.research_specialists import research_specialist_service
from server.services.skill_orchestrator import (
    PHASE_SKILL_BUNDLES,
    resolve_execution_contract,
    skill_orchestrator,
)
from server.services.skill_registry import skill_registry


@pytest.fixture(autouse=True)
def load_skills() -> None:
    root = Path(__file__).parents[2]
    skill_registry.scan_directory(root / "merak-skills")


def _options(family: str, archetype: str) -> dict:
    return {
        "research_family": family,
        "study_archetype": archetype,
        "target_venue": "test venue",
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }


@pytest.mark.parametrize(
    ("family", "archetype", "required", "forbidden"),
    [
        (
            "machine_learning",
            "algorithm_benchmark",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "ablation-planner", "domain-validation"},
            {"ethics-governance", "proof-writer", "system-profile"},
        ),
        (
            "computer_systems",
            "systems_testbed",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "system-profile", "domain-validation"},
            {"proof-writer", "ethics-governance"},
        ),
        (
            "clinical_biomedical",
            "diagnostic_prognostic",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "ethics-governance", "domain-validation"},
            {"proof-writer", "system-profile"},
        ),
        (
            "computational_biology",
            "omics_discovery",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "ethics-governance", "domain-validation"},
            {"proof-writer", "system-profile"},
        ),
        (
            "theoretical_formal",
            "formal_theory",
            {"domain-methodology", "proof-writer", "domain-validation"},
            {"data-quality-audit", "statistical-analysis-plan", "ethics-governance"},
        ),
        (
            "qualitative_humanities",
            "qualitative_mixed",
            {"domain-methodology", "data-quality-audit", "ethics-governance", "domain-validation"},
            {"statistical-analysis-plan", "proof-writer"},
        ),
        (
            "experimental_natural_science",
            "controlled_experiment",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "domain-validation"},
            {"ethics-governance", "proof-writer", "system-profile"},
        ),
        (
            "social_behavioral",
            "observational_cohort",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "ethics-governance", "domain-validation"},
            {"proof-writer", "system-profile"},
        ),
        (
            "engineering_systems",
            "systems_testbed",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "system-profile", "domain-validation"},
            {"proof-writer", "ethics-governance"},
        ),
        (
            "generic_quantitative",
            "generic_empirical",
            {"domain-methodology", "data-quality-audit", "statistical-analysis-plan", "domain-validation"},
            {"proof-writer", "ethics-governance", "system-profile"},
        ),
    ],
)
def test_profile_selects_required_specialist_subnodes(
    tmp_path: Path,
    family: str,
    archetype: str,
    required: set[str],
    forbidden: set[str],
) -> None:
    payload = research_specialist_service.prepare(
        tmp_path,
        "profile-run",
        "cross-domain research",
        _options(family, archetype),
        ["exp-design", "results"],
    )
    selected = {item["id"] for item in payload["subnodes"]}

    assert required <= selected
    assert not (forbidden & selected)
    assert payload["profile"]["family"] == family
    assert payload["profile"]["study_archetype"] == archetype
    assert all(item["execution_kind"] == "model_owned" for item in payload["subnodes"])


def test_results_analysis_does_not_invalidate_exp_design_specialists(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("planned analysis v1\n", encoding="utf-8")

    before = research_specialist_service.prepare(
        tmp_path,
        "digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    before_digests = {
        entry["id"]: entry["input_digest"]
        for entry in before["subnodes"]
    }

    analysis.write_text("planned analysis v2\n", encoding="utf-8")
    after = research_specialist_service.prepare(
        tmp_path,
        "digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    after_digests = {
        entry["id"]: entry["input_digest"]
        for entry in after["subnodes"]
    }

    assert (
        after_digests["domain-methodology"]
        == before_digests["domain-methodology"]
    )
    assert (
        after_digests["data-quality-audit"]
        == before_digests["data-quality-audit"]
    )
    assert (
        after_digests["statistical-analysis-plan"]
        == before_digests["statistical-analysis-plan"]
    )
    assert after_digests["ablation-planner"] == before_digests["ablation-planner"]
    assert after_digests["domain-validation"] != before_digests["domain-validation"]


def test_specialist_inputs_use_canonical_stage_paths() -> None:
    design_inputs = research_specialist_service._input_relatives("exp-design")
    result_inputs = research_specialist_service._input_relatives("results")

    assert "experiments/results/analysis.md" not in design_inputs
    assert "experiments/results/analysis.md" in result_inputs
    assert (
        "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
        in result_inputs
    )
    assert "experiments/results/PLANNED_RESULT_MANIFEST.json" not in result_inputs
    assert "CONTEXT.md" not in result_inputs


def test_design_repair_does_not_invalidate_design_specialists(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected.parent.mkdir(parents=True)
    selected.write_text('{"idea": "stable"}\n', encoding="utf-8")
    run_spec = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec.parent.mkdir(parents=True)
    run_spec.write_text('{"seeds": [1, 2]}\n', encoding="utf-8")

    before = research_specialist_service.prepare(
        tmp_path,
        "repair-digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    before_digests = {
        entry["id"]: entry["input_digest"] for entry in before["subnodes"]
    }

    run_spec.write_text('{"seeds": [1, 2, 3]}\n', encoding="utf-8")
    after = research_specialist_service.prepare(
        tmp_path,
        "repair-digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    after_digests = {
        entry["id"]: entry["input_digest"] for entry in after["subnodes"]
    }

    for specialist_id in (
        "domain-methodology",
        "data-quality-audit",
        "statistical-analysis-plan",
        "ablation-planner",
    ):
        assert after_digests[specialist_id] == before_digests[specialist_id]
    assert (
        after_digests["domain-validation"]
        != before_digests["domain-validation"]
    )


def test_literature_review_repair_only_invalidates_result_specialist(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected.parent.mkdir(parents=True)
    selected.write_text('{"idea": "stable"}\n', encoding="utf-8")
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Evidence map\nInitial precedents.\n", encoding="utf-8")

    before = research_specialist_service.prepare(
        tmp_path,
        "literature-digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    before_digests = {
        entry["id"]: entry["input_digest"] for entry in before["subnodes"]
    }

    survey.write_text(
        "# Evidence map\nInitial precedents plus reviewer-requested citation.\n",
        encoding="utf-8",
    )
    after = research_specialist_service.prepare(
        tmp_path,
        "literature-digest-run",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    after_digests = {
        entry["id"]: entry["input_digest"] for entry in after["subnodes"]
    }

    for specialist_id in (
        "domain-methodology",
        "data-quality-audit",
        "statistical-analysis-plan",
        "ablation-planner",
    ):
        assert after_digests[specialist_id] == before_digests[specialist_id]
    assert (
        after_digests["domain-validation"]
        != before_digests["domain-validation"]
    )


def test_partial_resume_preserves_completed_upstream_specialist_entries(
    tmp_path: Path,
) -> None:
    initial = research_specialist_service.prepare(
        tmp_path,
        "partial-resume-plan",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design", "results"],
    )
    design_ids = {
        entry["id"]
        for entry in initial["subnodes"]
        if entry["node_id"] == "exp-design"
    }

    resumed = research_specialist_service.prepare(
        tmp_path,
        "partial-resume-plan",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )

    assert design_ids <= {
        entry["id"]
        for entry in resumed["subnodes"]
        if entry["node_id"] == "exp-design"
    }


def test_same_plan_resume_preserves_specialist_invocation_provenance(
    tmp_path: Path,
) -> None:
    run_id = "provenance-resume-plan"
    payload = research_specialist_service.prepare(
        tmp_path,
        run_id,
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design"],
    )
    entry = next(item for item in payload["subnodes"] if item["id"] == "ablation-planner")
    artifact = tmp_path / entry["artifact"]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        "\n\n".join(entry["required_headings"]) + "\n" + ("Bounded design evidence. " * 20),
        encoding="utf-8",
    )
    trace_root = tmp_path / ".merak" / "skill-invocations"
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_path = trace_root / "resume_ablation-planner.json"
    session_id = "resume-specialist-session"
    trace_path.write_text(json.dumps({
        "status": "completed",
        "policy_loaded": True,
        "session_id": session_id,
        "skill": entry["skill"],
        "skill_sha256": "b" * 64,
        "skill_bytes": 2048,
    }), encoding="utf-8")
    entry.update({
        "status": "completed",
        "session_id": session_id,
        "model_provider": "openai",
        "model_name": "gpt-specialist",
        "invocation_trace": str(trace_path),
        "artifact_sha256": research_specialist_service._sha256(artifact),
    })
    research_specialist_service._atomic_write(
        research_specialist_service.plan_path(tmp_path, run_id), payload
    )

    resumed = research_specialist_service.prepare(
        tmp_path,
        run_id,
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design"],
    )
    resumed_entry = next(item for item in resumed["subnodes"] if item["id"] == "ablation-planner")
    assert resumed_entry["status"] == "completed"
    assert resumed_entry["invocation_trace"] == str(trace_path)
    assert resumed_entry["model_provider"] == "openai"
    assert resumed_entry["model_name"] == "gpt-specialist"


def test_prepare_recovers_lost_specialist_row_from_completed_trace(
    tmp_path: Path,
) -> None:
    payload = research_specialist_service.prepare(
        tmp_path,
        "trace-recovery-plan",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design"],
    )
    entry = next(
        item for item in payload["subnodes"]
        if item["id"] == "ablation-planner"
    )
    artifact = tmp_path / entry["artifact"]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        "# Ablation\n\nAblation and matched control design. " * 20,
        encoding="utf-8",
    )
    trace_root = tmp_path / ".merak" / "skill-invocations"
    trace_root.mkdir(parents=True)
    trace = trace_root / "completed_ablation-planner.json"
    trace.write_text(json.dumps({
        "status": "completed",
        "policy_loaded": True,
        "session_id": "recovered-session",
        "skill": "ablation-planner",
        "skill_sha256": "a" * 64,
        "skill_bytes": 1024,
        "finished_at": artifact.stat().st_mtime + 1,
    }), encoding="utf-8")
    payload["subnodes"] = []
    research_specialist_service._atomic_write(
        research_specialist_service.plan_path(
            tmp_path, "trace-recovery-plan"
        ),
        payload,
    )

    recovered = research_specialist_service.prepare(
        tmp_path,
        "trace-recovery-plan",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design"],
    )
    recovered_entry = next(
        item for item in recovered["subnodes"]
        if item["id"] == "ablation-planner"
    )

    assert recovered_entry["status"] == "completed"
    assert recovered_entry["session_id"] == "recovered-session"
    assert recovered_entry["recovered_from_project_trace"] is True


def test_transient_failure_preserves_prior_completed_specialist(
    tmp_path: Path,
) -> None:
    run_id = "transport-fallback-plan"
    payload = research_specialist_service.prepare(
        tmp_path,
        run_id,
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )
    entry = next(item for item in payload["subnodes"] if item["id"] == "domain-validation")
    artifact = tmp_path / entry["artifact"]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        "\n\n".join(entry["required_headings"]) + "\n" + ("Validation detail. " * 30),
        encoding="utf-8",
    )
    trace_root = tmp_path / ".merak" / "skill-invocations"
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_path = trace_root / "success_domain-validation.json"
    session_id = "successful-before-503"
    completed_at = time.time() - 10
    os.utime(artifact, (completed_at - 1, completed_at - 1))
    trace_path.write_text(json.dumps({
        "status": "completed",
        "policy_loaded": True,
        "session_id": session_id,
        "skill": entry["skill"],
        "skill_sha256": "c" * 64,
        "skill_bytes": 2048,
        "finished_at": completed_at,
    }), encoding="utf-8")
    # A later scientific input makes ordinary fresh-trace recovery ineligible;
    # only the explicitly transient fallback may preserve the known-good row.
    selected = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text('{"idea": "updated after prior specialist"}', encoding="utf-8")
    entry.update({
        "status": "failed",
        "error": "OpenAI API error 503: Service temporarily unavailable",
        "session_id": "failed-retry",
        "invocation_trace": "",
    })
    research_specialist_service._atomic_write(
        research_specialist_service.plan_path(tmp_path, run_id), payload
    )

    resumed = research_specialist_service.prepare(
        tmp_path,
        run_id,
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )
    resumed_entry = next(
        item for item in resumed["subnodes"] if item["id"] == "domain-validation"
    )

    assert resumed_entry["status"] == "completed"
    assert resumed_entry["session_id"] == session_id
    assert resumed_entry["invocation_trace"] == str(trace_path)
    assert resumed_entry["reused_after_transport_failure"] is True
    assert "503" in resumed_entry["transport_warning"]


def test_manifest_renderer_metadata_does_not_change_specialist_digest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "experiments" / "results" / "templates" / "PLANNED_RESULT_MANIFEST.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "generated_at": 1,
        "input_bundle_sha256": "1" * 64,
        "simulation_manifest_sha256": "2" * 64,
        "methods": ["A", "B"],
        "figure": {
            "output_sha256": "a" * 64,
            "output_bytes": 100,
            "source_data_sha256": {"data.csv": "d" * 64},
        },
    }), encoding="utf-8")
    first = research_specialist_service.prepare(
        tmp_path,
        "stable-renderer-digest",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )
    first_digest = next(
        item["input_digest"] for item in first["subnodes"]
        if item["id"] == "domain-validation"
    )
    manifest.write_text(json.dumps({
        "generated_at": 2,
        "input_bundle_sha256": "3" * 64,
        "simulation_manifest_sha256": "4" * 64,
        "methods": ["A", "B"],
        "figure": {
            "output_sha256": "b" * 64,
            "output_bytes": 200,
            "source_data_sha256": {"data.csv": "d" * 64},
        },
    }), encoding="utf-8")
    second = research_specialist_service.prepare(
        tmp_path,
        "stable-renderer-digest",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )
    second_digest = next(
        item["input_digest"] for item in second["subnodes"]
        if item["id"] == "domain-validation"
    )

    assert second_digest == first_digest

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["figure"]["source_data_sha256"]["data.csv"] = "e" * 64
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    third = research_specialist_service.prepare(
        tmp_path,
        "stable-renderer-digest",
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["results"],
    )
    third_digest = next(
        item["input_digest"] for item in third["subnodes"]
        if item["id"] == "domain-validation"
    )
    assert third_digest != second_digest


def test_specialist_gate_requires_hash_backed_canonical_artifacts(tmp_path: Path) -> None:
    run_id = "gate-run"
    payload = research_specialist_service.prepare(
        tmp_path,
        run_id,
        "machine learning benchmark",
        _options("machine_learning", "algorithm_benchmark"),
        ["exp-design"],
    )
    pending_gate = research_specialist_service.gate_node(tmp_path, run_id, "exp-design")
    assert pending_gate["accepted"] is False
    assert any("pending" in issue for issue in pending_gate["issues"])

    trace_root = tmp_path / ".merak" / "skill-invocations"
    trace_root.mkdir(parents=True, exist_ok=True)
    for entry in payload["subnodes"]:
        artifact = tmp_path / entry["artifact"]
        artifact.parent.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(str(marker) for marker in entry["required_headings"])
        artifact.write_text(body + "\n" + ("Evidence-bounded design detail. " * 20), encoding="utf-8")
        session_id = f"session-{entry['id']}"
        trace_path = trace_root / f"trace_{entry['skill']}.json"
        trace_path.write_text(json.dumps({
            "status": "completed",
            "policy_loaded": True,
            "session_id": session_id,
            "skill": entry["skill"],
            "skill_sha256": "a" * 64,
            "skill_bytes": 1024,
        }), encoding="utf-8")
        entry["status"] = "completed"
        entry["session_id"] = session_id
        entry["invocation_trace"] = str(trace_path)
        entry["artifact_sha256"] = research_specialist_service._sha256(artifact)
    research_specialist_service._atomic_write(
        research_specialist_service.plan_path(tmp_path, run_id), payload
    )

    accepted_gate = research_specialist_service.gate_node(tmp_path, run_id, "exp-design")
    assert accepted_gate["accepted"] is True
    assert accepted_gate["applicable"] is True


def test_execution_contracts_distinguish_model_runtime_and_hybrid_paths() -> None:
    assert resolve_execution_contract("lit", {}).kind == "model_owned"
    assert resolve_execution_contract("paper", {}).kind == "hybrid"
    audit = resolve_execution_contract("audit", {})
    assert audit.runtime_service == "five_layer_audit_coordinator"
    assert audit.model_execution_mode == "any_component"

    experiment = resolve_execution_contract("exp-run", {"run_experiment": True})
    assert experiment.kind == "runtime_owned"
    assert experiment.runtime_service == "experiment_scheduler"
    assert experiment.policy_required is False

    planned_results = resolve_execution_contract("results", {"run_experiment": False})
    assert planned_results.kind == "runtime_owned"
    assert planned_results.runtime_service == "planned_results_analysis"

    compile_contract = resolve_execution_contract("compile", {})
    assert compile_contract.kind == "runtime_owned"
    assert compile_contract.runtime_service == "paper_compiler"


@pytest.mark.parametrize(
    ("node_id", "options", "kind", "runtime_service", "policy_required"),
    [
        ("lit", {}, "model_owned", "", True),
        ("idea", {}, "model_owned", "", True),
        ("novelty", {}, "model_owned", "", True),
        ("exp-design", {}, "hybrid", "artifact_builders+research_gates", True),
        ("exp-run", {"run_experiment": True}, "runtime_owned", "experiment_scheduler", False),
        ("exp-run", {"run_experiment": False}, "runtime_owned", "experiment_placeholder_service", False),
        ("results", {"run_experiment": True}, "hybrid", "evidence_validation+research_gates", True),
        ("results", {"run_experiment": False}, "runtime_owned", "planned_results_analysis", False),
        ("figure", {}, "hybrid", "figure_renderers+figure_quality_gate", True),
        ("narrative", {}, "hybrid", "paper_plan_service+research_gates", True),
        ("paper", {}, "hybrid", "staged_paper_drafting+paper_gates", True),
        ("review", {}, "hybrid", "cross_model_review_coordinator", True),
        ("audit", {}, "hybrid", "five_layer_audit_coordinator", True),
        ("compile", {}, "runtime_owned", "paper_compiler", False),
        ("ppt", {}, "hybrid", "scientific_slide_service+paper_compiler", True),
    ],
)
def test_all_macro_nodes_declare_truthful_execution_ownership(
    node_id: str,
    options: dict,
    kind: str,
    runtime_service: str,
    policy_required: bool,
) -> None:
    contract = resolve_execution_contract(node_id, options)
    assert contract.kind == kind
    assert contract.runtime_service == runtime_service
    assert contract.policy_required is policy_required


def test_completed_skill_requires_policy_hash_and_model_session_to_count(
    tmp_path: Path,
) -> None:
    plan = skill_orchestrator.select("lit", "/research-lit", str(tmp_path), {})
    path = skill_orchestrator.record(str(tmp_path), "proof-run", plan)

    skill_orchestrator.mark_execution(
        str(tmp_path),
        "proof-run",
        "lit",
        "research-lit",
        "completed",
        policy_loaded=True,
        execution_kind="model_owned",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["unique_skills_executed"] == []
    assert payload["unverified_completed_skills"] == ["research-lit"]
    assert payload["stages"]["lit"]["invocations"][-1]["execution_verified"] is False

    skill_orchestrator.mark_execution(
        str(tmp_path),
        "proof-run",
        "lit",
        "research-lit",
        "completed",
        session_id="model-session-1",
        policy_loaded=True,
        execution_kind="model_owned",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["unique_skills_executed"] == ["research-lit"]
    assert payload["verified_model_invocation_count"] == 1
    assert payload["unverified_completed_skills"] == []
    assert payload["stages"]["lit"]["invocations"][-1]["execution_verified"] is True
    assert payload["stage_execution"]["lit"]["model_execution_verified"] is True
    assert payload["stage_execution"]["lit"]["runtime_execution_verified"] is False


def test_runtime_trace_does_not_claim_that_a_model_skill_executed(tmp_path: Path) -> None:
    plan = skill_orchestrator.select(
        "compile",
        "/paper-compile",
        str(tmp_path),
        {"run_experiment": False},
    )
    path = skill_orchestrator.record(str(tmp_path), "runtime-run", plan)
    skill_orchestrator.mark_runtime_execution(
        str(tmp_path),
        "runtime-run",
        "compile",
        "paper_compiler",
        "completed",
        operation_id="compile-1",
        output="paper/main.pdf",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    stage = payload["stages"]["compile"]

    assert payload["schema"] == 2
    assert stage["primary_status"] == "not_applicable_runtime_owned"
    assert stage["runtime_status"] == "completed"
    assert stage["runtime_invocations"][-1]["policy_loaded"] is False
    assert payload["unique_skills_executed"] == []
    assert payload["runtime_services_executed"] == ["paper_compiler"]
    assert payload["stage_execution"]["compile"]["runtime_execution_verified"] is True
    assert payload["stage_execution"]["compile"]["model_execution_verified"] is False


def test_new_cross_domain_skills_have_loadable_full_policies() -> None:
    for skill_name in (
        "domain-methodology",
        "statistical-analysis-plan",
        "data-quality-audit",
        "domain-validation",
        "ethics-governance",
    ):
        policy = skill_orchestrator.full_policy(skill_name)
        assert policy.startswith("---")
        assert len(policy) > 500


def test_exp_design_execution_gate_accepts_verified_staged_component_and_runtime(
    tmp_path: Path,
) -> None:
    plan = skill_orchestrator.select(
        "exp-design",
        "/experiment-plan",
        str(tmp_path),
        {"run_experiment": True},
    )
    skill_orchestrator.record(str(tmp_path), "hybrid-proof", plan)
    skill_orchestrator.mark_execution(
        str(tmp_path),
        "hybrid-proof",
        "exp-design",
        "domain-methodology",
        "completed",
        role="profile_specialist",
        session_id="delegate-session",
        policy_loaded=True,
        execution_kind="model_owned",
    )
    skill_orchestrator.mark_runtime_execution(
        str(tmp_path),
        "hybrid-proof",
        "exp-design",
        plan.runtime_service,
        "completed",
        operation_id="gate-operation",
    )

    staged_component = skill_orchestrator.execution_gate(
        str(tmp_path), "hybrid-proof", "exp-design"
    )
    assert plan.model_execution_mode == "any_component"
    assert staged_component["accepted"] is True
    assert staged_component["model_execution_verified"] is True
    assert staged_component["primary_model_execution_verified"] is False
    assert staged_component["runtime_execution_verified"] is True

    skill_orchestrator.mark_execution(
        str(tmp_path),
        "hybrid-proof",
        "exp-design",
        plan.primary,
        "completed",
        role="primary",
        session_id="owner-session",
        policy_loaded=True,
        execution_kind="hybrid",
    )
    accepted = skill_orchestrator.execution_gate(
        str(tmp_path), "hybrid-proof", "exp-design"
    )
    assert accepted["accepted"] is True
    assert accepted["primary_skill"] == plan.primary
    assert accepted["primary_model_execution_verified"] is True


def test_composite_audit_accepts_verified_component_without_faking_primary(
    tmp_path: Path,
) -> None:
    plan = skill_orchestrator.select(
        "audit",
        "/experiment-audit",
        str(tmp_path),
        {"run_experiment": False},
    )
    skill_orchestrator.record(str(tmp_path), "audit-components", plan)
    skill_orchestrator.mark_execution(
        str(tmp_path),
        "audit-components",
        "audit",
        "result-to-claim",
        "completed",
        role="audit_layer",
        session_id="result-claim-session",
        policy_loaded=True,
        execution_kind="hybrid",
    )
    skill_orchestrator.mark_runtime_execution(
        str(tmp_path),
        "audit-components",
        "audit",
        plan.runtime_service,
        "completed",
        operation_id="audit-runtime",
    )

    gate = skill_orchestrator.execution_gate(
        str(tmp_path),
        "audit-components",
        "audit",
    )

    assert gate["accepted"] is True
    assert gate["model_execution_mode"] == "any_component"
    assert gate["model_requirement_verified"] is True
    assert gate["model_execution_verified"] is True
    assert gate["primary_model_execution_verified"] is False
    assert gate["runtime_execution_verified"] is True


def test_cross_domain_stage_owners_load_complete_policies() -> None:
    expected = {
        "idea": "domain-idea-discovery",
        "novelty": "domain-novelty-check",
        "exp-design": "domain-experiment-plan",
        "results": "domain-results-analysis",
        "narrative": "domain-narrative",
        "paper": "domain-paper-write",
        "review": "domain-review-loop",
    }
    for node_id, skill_name in expected.items():
        plan = skill_orchestrator.select(node_id, f"/{skill_name}", ".", {})
        assert plan.primary == skill_name
        policy = skill_orchestrator.full_policy(skill_name)
        assert policy.startswith("---")
        assert len(policy) > 900


def test_workflow_execution_gate_identifies_the_unverified_stage(tmp_path: Path) -> None:
    lit_plan = skill_orchestrator.select("lit", "/research-lit", str(tmp_path), {})
    figure_plan = skill_orchestrator.select("figure", "/paper-figure", str(tmp_path), {})
    skill_orchestrator.record(str(tmp_path), "aggregate-run", lit_plan)
    skill_orchestrator.mark_execution(
        str(tmp_path), "aggregate-run", "lit", lit_plan.primary, "completed",
        role="primary", session_id="lit-session", policy_loaded=True,
        execution_kind="model_owned",
    )
    skill_orchestrator.record(str(tmp_path), "aggregate-run", figure_plan)

    rejected = skill_orchestrator.workflow_execution_gate(
        str(tmp_path), "aggregate-run", ["lit", "figure"]
    )
    assert rejected["accepted"] is False
    assert any(issue.startswith("figure:") for issue in rejected["issues"])

    skill_orchestrator.mark_execution(
        str(tmp_path), "aggregate-run", "figure", figure_plan.primary, "completed",
        role="primary", session_id="figure-session", policy_loaded=True,
        execution_kind="hybrid",
    )
    skill_orchestrator.mark_runtime_execution(
        str(tmp_path), "aggregate-run", "figure", figure_plan.runtime_service,
        "completed", operation_id="figure-gate",
    )
    still_rejected = skill_orchestrator.workflow_execution_gate(
        str(tmp_path), "aggregate-run", ["lit", "figure"]
    )
    assert still_rejected["accepted"] is False
    assert any("FIGURE_SPECS.json" in issue for issue in still_rejected["issues"])


def test_every_model_or_hybrid_macro_node_has_a_complete_owner_policy() -> None:
    for node_id, bundle in PHASE_SKILL_BUNDLES.items():
        contract = resolve_execution_contract(
            node_id, {"run_experiment": True}
        )
        primary = str(bundle["primary"])
        metadata = skill_registry.get_skill(primary)
        assert metadata is not None, f"{node_id}: missing /{primary}"
        if contract.policy_required:
            policy = skill_orchestrator.full_policy(primary)
            assert len(policy) > 500, f"{node_id}: thin /{primary}"
        else:
            assert contract.kind == "runtime_owned"
