from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.services.scientific_narrative import scientific_narrative_service
from server.services.node_risk_audit import node_risk_audit_service


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_narrative_fallback_is_claim_grounded_and_does_not_invent_results(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Contract-Grounded Catalyst Stability",
        "problem_statement": "Catalyst grains coarsen under repeated thermal cycles.",
        "hypothesis": "A surface treatment slows grain coarsening.",
        "claims": [{"id": "C1", "statement": "The treatment lowers the coarsening rate."}],
        "mechanisms": [{
            "id": "M1",
            "name": "Surface-energy modulation",
            "description": "The treatment changes the coarsening pathway.",
            "required": True,
        }],
        "falsification_conditions": ["The untreated control has the same coarsening rate."],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {
        "claim_evidence_plan": [{
            "idea_claim_id": "C1",
            "outcomes": ["Paired microscopy-derived coarsening rate"],
            "failure_conditions": ["The effect does not exceed the null margin"],
        }],
    })
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("# Planned analysis\nExperiments were not executed.\n", encoding="utf-8")
    _write_json(tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json", {
        "evidence_mode": "planned",
        "assets": [{
            "id": "method_architecture",
            "kind": "figure",
            "scientific_role": "method",
            "scientific_question": "How does M1 operationalize the hypothesis?",
            "evidence_status": "implemented_design",
        }],
    })
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Survey\nPrior work context.\n", encoding="utf-8")

    result = scientific_narrative_service.ensure(tmp_path, "materials discovery")
    narrative = (tmp_path / "NARRATIVE_REPORT.md").read_text(encoding="utf-8")

    assert result["generated"] is True
    assert "Contract-Grounded Catalyst Stability" in narrative
    assert "Surface-energy modulation" in narrative
    assert "Paired microscopy-derived coarsening rate" in narrative
    assert "PENDING_NOT_EXECUTED" in narrative
    assert "No accuracy, effect size, significance, superiority" in narrative
    assert "outperforms" not in narrative
    own_findings = node_risk_audit_service._audit_narrative(
        tmp_path,
        {"run_experiment": False},
    )
    assert not [item for item in own_findings if item.get("severity") == "blocker"]
    build = json.loads((tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8"))
    assert build["output_sha256"] == hashlib.sha256(
        (tmp_path / "NARRATIVE_REPORT.md").read_bytes()
    ).hexdigest()

    _write_json(
        tmp_path / "figures" / "FIGURE_MANIFEST.json",
        {"schema": 1, "figures": []},
    )
    (tmp_path / "NARRATIVE_REPORT.md").write_text(
        "The proposed method significantly outperforms all baselines.\n",
        encoding="utf-8",
    )
    repaired = scientific_narrative_service.ensure(tmp_path, "materials discovery")
    repaired_text = (tmp_path / "NARRATIVE_REPORT.md").read_text(encoding="utf-8")
    repaired_build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )
    assert repaired["generated"] is True
    assert "significantly outperforms" not in repaired_text
    assert "figures/FIGURE_MANIFEST.json" not in repaired_build["sources"]
    assert not [
        item
        for item in node_risk_audit_service._audit_narrative(
            tmp_path,
            {"run_experiment": False},
        )
        if item.get("severity") == "blocker"
    ]


def test_simulation_narrative_synthesizes_complete_benchmark_findings(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Robust Representation Benchmark",
        "problem_statement": "Representation quality degrades under shift.",
        "hypothesis": "The full mechanism improves robustness within the benchmark.",
        "claims": [{"id": "C1", "statement": "The full mechanism leads matched controls."}],
        "mechanisms": [{
            "id": "M1",
            "name": "Shift-aware consistency",
            "description": "Aligns representations across controlled perturbations.",
            "required": True,
        }],
        "falsification_conditions": ["Matched controls occupy the same uncertainty interval."],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {
        "claim_evidence_plan": [{
            "idea_claim_id": "C1",
            "outcomes": ["Primary comparison and component removal"],
            "failure_conditions": ["The matched control is not worse"],
        }],
    })
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text(
        "# Deterministic Benchmark Result Analysis\n\n"
        "The full configuration leads the primary comparison within the defined "
        "benchmark, while stress and failure slices bound the conclusion.\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json",
        {
            "schema": 5,
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        },
    )
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Survey\nPrior benchmark literature.\n", encoding="utf-8")

    result = scientific_narrative_service.ensure(tmp_path, "robust learning")
    narrative = (tmp_path / "NARRATIVE_REPORT.md").read_text(encoding="utf-8")

    assert result["evidence_mode"] == "synthetic_preview"
    assert "BENCHMARK_RESULT_REVIEW" in narrative
    assert "UNRESOLVED" in narrative
    assert "not proof that the registered research was executed" in narrative
    assert "current source-bound benchmark decision audit is unavailable" in narrative
    assert "planning previews are NOT EVIDENCE" not in narrative
    assert "research protocol, not a validated performance claim" not in narrative
    findings = node_risk_audit_service._audit_narrative(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    assert not [item for item in findings if item.get("severity") == "blocker"]


def test_narrative_mechanism_coverage_accepts_publication_names_without_internal_ids(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Auditable comparison",
        "claims": [],
        "mechanisms": [
            {"id": "M2", "name": "运行级证据账本"},
            {"id": "M3", "name": "协议替代解释消融"},
        ],
    })
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text(
        "# Auditable comparison\n\n"
        "运行级证据账本连接测量与配置。协议替代解释消融采用匹配对照。\n"
        "## 局限\n结论限于受控评估范围，并报告置信区间。\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_narrative(tmp_path, {})

    assert not any(item.get("id") == "NAR-MECH-001" for item in findings)


def test_evidence_mode_switch_regenerates_managed_narrative(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Mode-switch benchmark",
        "problem_statement": "A controlled comparison is required.",
        "hypothesis": "The registered mechanism improves the primary endpoint.",
        "claims": [{"id": "C1", "statement": "The mechanism improves the endpoint."}],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {
        "claim_evidence_plan": [{
            "idea_claim_id": "C1",
            "outcomes": ["Registered primary comparison"],
            "failure_conditions": ["The registered margin is not met"],
        }],
    })
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Survey\nPrior controlled comparisons.\n", encoding="utf-8")
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text(
        "# Planned analysis\nThe experiment was not executed.\n",
        encoding="utf-8",
    )
    manifest = (
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json"
    )
    _write_json(manifest, {
        "schema": 5,
        "evidence_mode": "design_only",
        "submission_eligible": False,
    })

    scientific_narrative_service.ensure(tmp_path, "mode switch")
    planned_text = (tmp_path / "NARRATIVE_REPORT.md").read_text(encoding="utf-8")
    assert "PENDING_NOT_EXECUTED" in planned_text

    analysis.write_text(
        "# Deterministic Benchmark Result Analysis\n"
        "The full configuration leads the registered primary comparison.\n",
        encoding="utf-8",
    )
    _write_json(manifest, {
        "schema": 5,
        "evidence_mode": "synthetic_preview",
        "submission_eligible": False,
    })
    switched = scientific_narrative_service.ensure(tmp_path, "mode switch")
    switched_text = (tmp_path / "NARRATIVE_REPORT.md").read_text(encoding="utf-8")

    assert switched["generated"] is True
    assert switched["evidence_mode"] == "synthetic_preview"
    assert "BENCHMARK_RESULT_REVIEW" in switched_text
    assert "planning previews are NOT EVIDENCE" not in switched_text
    assert "research protocol, not a validated performance claim" not in switched_text


def test_existing_narrative_is_not_overwritten(tmp_path: Path) -> None:
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text("Researcher-authored narrative.\n", encoding="utf-8")

    result = scientific_narrative_service.ensure(tmp_path, "test")
    build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )

    assert result["generated"] is False
    assert result["provenance_recorded"] is True
    assert narrative.read_text(encoding="utf-8") == "Researcher-authored narrative.\n"
    assert build["generator"] == "researcher-authored:source-bound"
    assert build["output_sha256"] == hashlib.sha256(narrative.read_bytes()).hexdigest()


def test_researcher_narrative_is_preserved_and_marked_stale_on_source_drift(
    tmp_path: Path,
) -> None:
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Initial evidence\n", encoding="utf-8")
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text("Researcher-authored interpretation.\n", encoding="utf-8")

    scientific_narrative_service.ensure(tmp_path, "test")
    original_build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )
    survey.write_text("# Revised evidence\n", encoding="utf-8")

    result = scientific_narrative_service.ensure(tmp_path, "test")
    current_build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )

    assert result["generated"] is False
    assert result["source_drift"] is True
    assert narrative.read_text(encoding="utf-8") == "Researcher-authored interpretation.\n"
    assert current_build == original_build
    findings = node_risk_audit_service._audit_narrative(tmp_path, {})
    assert any(item.get("id") == "NAR-PROV-003" for item in findings)


def test_automatic_workflow_rebuilds_stale_unrecorded_narrative(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("C1 — SUPPORTED; 10 qualifying reversals.\n", encoding="utf-8")
    _write_json(
        tmp_path / "experiments" / "results" / "templates"
        / "PLANNED_RESULT_MANIFEST.json",
        {"evidence_mode": "synthetic_preview"},
    )
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text("Stale prior-worker conclusion: C1 is not supported.\n", encoding="utf-8")

    result = scientific_narrative_service.ensure(
        tmp_path,
        "test",
        preserve_researcher_authored=False,
    )
    build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )

    assert result["generated"] is True
    assert "10 qualifying reversals" not in narrative.read_text(encoding="utf-8")
    assert "UNRESOLVED" in narrative.read_text(encoding="utf-8")
    assert build["generator"] == "deterministic:evidence-bounded-narrative"
    assert "experiments/results/analysis.md" in build["sources"]


def test_revised_researcher_narrative_rebinds_current_sources(tmp_path: Path) -> None:
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Initial evidence\n", encoding="utf-8")
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text("Initial interpretation.\n", encoding="utf-8")
    scientific_narrative_service.ensure(tmp_path, "test")

    survey.write_text("# Revised evidence\n", encoding="utf-8")
    narrative.write_text("Revised researcher interpretation.\n", encoding="utf-8")
    result = scientific_narrative_service.ensure(tmp_path, "test")
    build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )

    assert result["generated"] is False
    assert result["provenance_recorded"] is True
    assert narrative.read_text(encoding="utf-8") == "Revised researcher interpretation.\n"
    assert build["output_sha256"] == hashlib.sha256(narrative.read_bytes()).hexdigest()
    assert not any(
        item.get("id") in {"NAR-PROV-003", "NAR-PROV-004"}
        for item in node_risk_audit_service._audit_narrative(tmp_path, {})
    )

def test_narrative_source_hash_ignores_only_volatile_json_metadata(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "ideas" / "SELECTED_IDEA.json", {
        "title": "Stable source test",
        "claims": [{"id": "C1", "statement": "A semantic claim."}],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", {})
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("Experiments were not executed; claims remain pending.\n", encoding="utf-8")
    manifest = (
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json"
    )
    _write_json(manifest, {
        "schema": 3,
        "generated_at": 100.0,
        "evidence_mode": "design_only",
        "experiments": [{"id": "primary", "updated_at": 101.0}],
    })
    survey = tmp_path / "literature" / "survey.md"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Stable survey\n", encoding="utf-8")

    first = scientific_narrative_service.ensure(tmp_path, "test")
    original_narrative = (tmp_path / "NARRATIVE_REPORT.md").read_bytes()
    original_build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )
    assert first["generated"] is True

    _write_json(manifest, {
        "schema": 3,
        "generated_at": 200.0,
        "evidence_mode": "design_only",
        "experiments": [{"id": "primary", "updated_at": 201.0}],
    })
    unchanged = scientific_narrative_service.ensure(tmp_path, "test")
    assert unchanged["generated"] is False
    assert (tmp_path / "NARRATIVE_REPORT.md").read_bytes() == original_narrative
    assert json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    ) == original_build
    assert not any(
        item.get("id") == "NAR-PROV-003"
        for item in node_risk_audit_service._audit_narrative(tmp_path, {})
    )

    _write_json(manifest, {
        "schema": 3,
        "generated_at": 300.0,
        "evidence_mode": "executed",
        "experiments": [{"id": "primary", "updated_at": 301.0}],
    })
    assert any(
        item.get("id") == "NAR-PROV-003"
        for item in node_risk_audit_service._audit_narrative(tmp_path, {})
    )
    changed = scientific_narrative_service.ensure(tmp_path, "test")
    assert changed["generated"] is True
    changed_build = json.loads(
        (tmp_path / ".merak" / "NARRATIVE_BUILD.json").read_text(encoding="utf-8")
    )
    assert (
        changed_build["source_bundle_sha256"]
        != original_build["source_bundle_sha256"]
    )
