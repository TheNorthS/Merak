from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import pytest

from server.services.node_risk_audit import node_risk_audit_service
from server.services.experiment_placeholders import experiment_placeholder_service
from server.services.research_quality import research_quality_service
from server.services.scientific_slides import scientific_slide_service
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_RENDERER_VERSION,
    simulation_manifest_contract_issues,
)
from server.services.paper_artifacts import simulation_manifest_semantic_hash
from server.services.workflow_inputs import artifact_state, artifact_state_equal
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState


def _project_contract(project: Path) -> None:
    ideas = project / "ideas"
    experiments = project / "experiments"
    ideas.mkdir(parents=True, exist_ok=True)
    experiments.mkdir(parents=True, exist_ok=True)
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2,
        "title": "Prospective Method",
        "hypothesis": "The mechanism may improve transfer after it is tested.",
        "claims": [{"id": "C1"}],
        "publication": {
            "language": "en", "title": "Prospective Method", "method_name": "Prospective Method",
            "contribution_type": "objective_mechanism",
            "comparator_names": ["Declared reference condition", "Prospective Method"],
        },
    }), encoding="utf-8")
    (experiments / "METHOD_CONTRACT.json").write_text(json.dumps({
        "schema": 2,
        "claim_evidence_plan": [{
            "idea_claim_id": "C1",
            "outcomes": [
                "The proposed method significantly outperforms the matched baseline.",
            ],
            "failure_conditions": [
                "A matched baseline outperforms the proposed method.",
            ],
        }],
    }), encoding="utf-8")


def test_planned_results_fixture_declares_comparators_without_execution_evidence(tmp_path: Path) -> None:
    _project_contract(tmp_path)
    selected = json.loads((tmp_path / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8"))
    assert selected["publication"]["comparator_names"] == ["Declared reference condition", "Prospective Method"]
    assert "status" not in selected and not (tmp_path / "experiments/results").exists()
    from server.services.planned_study_contract import planned_study_contract
    selected["publication"].pop("comparator_names")
    with pytest.raises(ValueError, match="publication comparator names are required"):
        planned_study_contract(selected, {}, {}, {}, {"study_archetype": "generic_empirical"}, "Declared study")


def _run(
    project: Path,
    run_id: str = "planned-results",
    evidence_mode: str = "design_only",
) -> WorkflowRun:
    return WorkflowRun(
        id=run_id,
        project_path=str(project),
        nodes=[],
        status="running",
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": evidence_mode,
        },
    )


def test_planned_results_render_support_language_as_prospective_conditions(
    tmp_path: Path,
) -> None:
    _project_contract(tmp_path)
    engine = WorkflowEngine()
    run = _run(tmp_path)

    engine._ensure_planned_results_analysis(run, "test direction")

    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    text = analysis.read_text(encoding="utf-8")
    assert "Hypothesis to be tested (PENDING):" in text
    assert "To be tested: The proposed method significantly outperforms" in text
    assert "The claim would be rejected if A matched baseline outperforms" in text
    findings = node_risk_audit_service._audit_results(
        tmp_path,
        run.options,
    )
    assert not any(item["id"] == "RESULT-MODE-002" for item in findings)


def test_planned_results_reconcile_existing_generated_artifact_by_content(
    tmp_path: Path,
) -> None:
    _project_contract(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        "# Planned Result Analysis (NOT EVIDENCE)\n\n"
        "Prospective Method significantly outperforms all baselines.\n",
        encoding="utf-8",
    )
    before = artifact_state(analysis)
    engine = WorkflowEngine()
    run = _run(tmp_path)

    engine._ensure_planned_results_analysis(run, "test direction")
    after = artifact_state(analysis)

    assert not artifact_state_equal(before, after)
    first_repair = analysis.read_text(encoding="utf-8")
    engine._ensure_planned_results_analysis(run, "test direction")
    assert analysis.read_text(encoding="utf-8") == first_repair


def test_design_only_results_quality_accepts_explicit_no_run_provenance(
    tmp_path: Path,
) -> None:
    """A planned study must not loop forever looking for a nonexistent run ID."""
    _project_contract(tmp_path)
    engine = WorkflowEngine()
    run = _run(tmp_path)

    engine._ensure_planned_results_analysis(run, "test direction")
    quality = research_quality_service.evaluate(
        str(tmp_path),
        "results",
        "submission",
        "rigorous",
    )

    assert quality["passed"] is True, quality
    provenance = next(
        item for item in quality["dimensions"] if item["name"] == "provenance"
    )
    assert "structured:planned_no_run" in provenance["matched_patterns"]


def test_simulation_results_analysis_is_complete_and_not_protocol_mode(
    tmp_path: Path,
) -> None:
    _project_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "deterministic benchmark test",
            evidence_mode="synthetic_preview",
            research_family="machine_learning",
            study_archetype="algorithm_benchmark",
        )
    )
    engine = WorkflowEngine()
    run = _run(tmp_path, evidence_mode="synthetic_preview")

    result = engine._ensure_planned_results_analysis(
        run,
        "deterministic benchmark test",
    )
    analysis_path = tmp_path / "experiments" / "results" / "analysis.md"
    analysis = analysis_path.read_text(encoding="utf-8")
    simulated_dir = tmp_path / "experiments" / "results" / "simulated"
    manifest_path = simulated_dir / "SIMULATION_MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    manifest_sha256 = simulation_manifest_semantic_hash(manifest)
    main_rows = engine._simulation_result_rows(
        simulated_dir / "main_comparison.csv"
    )
    source_run_ids = sorted({row["source_run_id"] for row in main_rows})

    assert result == "Deterministic benchmark result analysis written."
    assert "# Deterministic Benchmark Result Analysis" in analysis
    for heading in (
        "## Primary comparison",
        "## Component analysis",
        "## Training dynamics",
        "## Robustness and sensitivity",
        "## Failure and error analysis",
        "## Calibration and selective risk",
        "## Performance--resource trade-off",
        "## Claim-level interpretation",
        "## Metric provenance and run identity",
        "## Registered cross-axis paired family",
    ):
        assert heading in analysis
    assert f"`simulation_id={manifest['simulation_id']}`" in analysis
    assert f"`seed={manifest['simulation_seed']}`" in analysis
    assert (
        "`experiments/results/simulated/SIMULATION_MANIFEST.json`"
        in analysis
    )
    assert f"`{manifest_sha256}`" in analysis
    for source_run_id in source_run_ids:
        assert f"`source_run_id={source_run_id}`" in analysis
    assert "95% seed-summary interval" in analysis
    pair_contract = manifest["registered_pair_contract"]
    assert (
        f"{pair_contract['observed_comparison_count']} unordered paired comparisons "
        f"across {pair_contract['model_count']} declared models"
    ) in analysis
    assert (
        f"{pair_contract['observed_comparison_count']} ordered paired comparisons"
        not in analysis
    )
    assert "Provenance joins are complete" in analysis
    assert "benchmark scope" in analysis
    assert "C1 — UNRESOLVED" in analysis
    assert "no source bound registered claim decision rule" in analysis
    assert "C1 — SUPPORTED" not in analysis
    assert "C1 — PENDING" not in analysis
    assert "NOT EVIDENCE" not in analysis
    assert "PENDING_NOT_EXECUTED" not in analysis
    assert "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS" not in analysis
    findings = node_risk_audit_service._audit_results(
        tmp_path,
        run.options,
    )
    assert not [item for item in findings if item.get("severity") == "blocker"]
    quality = research_quality_service.evaluate(
        str(tmp_path),
        "results",
        "submission",
        "rigorous",
    )
    assert quality["passed"] is True, quality
    assert quality["score"] == 1.0

    before_repeat = artifact_state(analysis_path)
    engine._ensure_planned_results_analysis(
        run,
        "deterministic benchmark test",
    )
    assert artifact_state_equal(before_repeat, artifact_state(analysis_path))

    manifest.pop("simulation_id", None)
    manifest.pop("simulation_seed", None)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for csv_path in simulated_dir.glob("*.csv"):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            fieldnames = list(rows[0]) if rows else []
        for row in rows:
            for key in ("simulation_seed", "seed", "source_run_id"):
                if key in row:
                    row[key] = ""
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    engine._ensure_planned_results_analysis(
        run,
        "deterministic benchmark test",
    )
    unbound_analysis = analysis_path.read_text(encoding="utf-8")
    assert "## Package identity status" in unbound_analysis
    assert "## Metric provenance and run identity" not in unbound_analysis
    assert "simulation_id=" not in unbound_analysis
    assert "source_run_id=" not in unbound_analysis
    assert "merak-structural-simulation-v1" not in unbound_analysis


def test_simulation_analysis_ignores_renderer_only_manifest_drift(
    tmp_path: Path,
) -> None:
    """Figure/table re-render metadata must not rewrite scientific analysis."""
    _project_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "renderer stability benchmark",
            evidence_mode="synthetic_preview",
            research_family="machine_learning",
            study_archetype="algorithm_benchmark",
        )
    )
    engine = WorkflowEngine()
    run = _run(tmp_path, evidence_mode="synthetic_preview")
    engine._ensure_planned_results_analysis(run, "renderer stability benchmark")
    analysis_path = tmp_path / "experiments" / "results" / "analysis.md"
    before = analysis_path.read_text(encoding="utf-8")
    manifest_path = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic_before = simulation_manifest_semantic_hash(manifest)
    manifest["generated_at"] = float(manifest.get("generated_at") or 0) + 12345
    manifest["renderer_version"] = int(manifest.get("renderer_version") or 0) + 1
    if manifest.get("figure_files"):
        manifest["figure_files"][0]["output_sha256"] = {
            "pdf": "f" * 64,
            "svg": "e" * 64,
            "png": "d" * 64,
        }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert simulation_manifest_semantic_hash(manifest) == semantic_before

    engine._ensure_planned_results_analysis(run, "renderer stability benchmark")
    assert analysis_path.read_text(encoding="utf-8") == before
    findings = node_risk_audit_service._audit_results(tmp_path, run.options)
    assert not any(item.get("id") == "RESULT-STALE-001" for item in findings)


@pytest.mark.parametrize(
    (
        "research_family",
        "study_archetype",
        "expected_headings",
        "expected_axis_terms",
        "forbidden_headings",
    ),
    [
        (
            "clinical_biomedical",
            "diagnostic_prognostic",
            (
                "Primary clinical effect comparison",
                "Clinical specification and estimand sensitivity",
                "Validation trajectory",
                "Population and protocol robustness",
                "Prespecified subgroup outcome analysis",
                "Clinical utility and retained-coverage analysis",
                "Clinical feasibility and acquisition burden",
            ),
            ("validation fraction", "clinical specification", "subgroup"),
            ("Training dynamics", "Failure and error analysis"),
        ),
        (
            "theoretical_formal",
            "formal_theory",
            (
                "Theorem guarantee and reference-bound comparison",
                "Assumption-necessity analysis",
                "Proof-construction progression",
                "Assumption-relaxation robustness",
                "Counterexample and boundary-regime analysis",
                "Assumption coverage versus guarantee gap",
                "Proof complexity and verification burden",
            ),
            ("proof stage", "assumption setting", "counterexample regime"),
            ("Training dynamics", "Failure and error analysis"),
        ),
        (
            "qualitative_humanities",
            "qualitative_mixed",
            (
                "Cross-source thematic comparison",
                "Triangulation and coding sensitivity",
                "Thematic saturation progression",
                "Negative-case robustness",
                "Divergent-case and coder-disagreement analysis",
                "Source coverage versus unresolved contradiction",
                "Auditability and coding-burden trade-off",
            ),
            ("cases reviewed", "analytic specification", "divergent case"),
            ("Training dynamics", "Failure and error analysis"),
        ),
    ],
)
def test_simulation_analysis_uses_manifest_domain_roles_and_axes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_family: str,
    study_archetype: str,
    expected_headings: tuple[str, ...],
    expected_axis_terms: tuple[str, ...],
    forbidden_headings: tuple[str, ...],
) -> None:
    async def render_without_matplotlib(script: Path) -> tuple[bool, str]:
        script.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% domain analysis test\n")
        script.with_suffix(".svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            encoding="utf-8",
        )
        script.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return True, ""

    monkeypatch.setattr(
        experiment_placeholder_service,
        "_render",
        render_without_matplotlib,
    )
    _project_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            f"{research_family} deterministic benchmark",
            evidence_mode="synthetic_preview",
            research_family=research_family,
            study_archetype=study_archetype,
        )
    )

    engine = WorkflowEngine()
    engine._ensure_planned_results_analysis(
        _run(tmp_path, evidence_mode="synthetic_preview"),
        f"{research_family} deterministic benchmark",
    )
    analysis = (
        tmp_path / "experiments" / "results" / "analysis.md"
    ).read_text(encoding="utf-8")

    assert "## Metric provenance and run identity" in analysis
    assert "## Package completeness" not in analysis
    for heading in expected_headings:
        assert f"## {heading}" in analysis
    lowered = analysis.casefold()
    for term in expected_axis_terms:
        assert term in lowered
    for heading in forbidden_headings:
        assert f"## {heading}" not in analysis


def test_generic_rmse_simulation_uses_lower_is_better_and_rejects_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def render_without_matplotlib(script: Path) -> tuple[bool, str]:
        script.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% rmse direction test\n")
        script.with_suffix(".svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            encoding="utf-8",
        )
        script.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return True, ""

    monkeypatch.setattr(
        experiment_placeholder_service,
        "_render",
        render_without_matplotlib,
    )
    _project_contract(tmp_path)
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "experiment:\n  primary_metric: RMSE\n",
        encoding="utf-8",
    )
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "generic RMSE benchmark",
            evidence_mode="synthetic_preview",
            research_family="generic_quantitative",
            study_archetype="generic_empirical",
        )
    )
    simulated = tmp_path / "experiments" / "results" / "simulated"
    manifest_path = simulated / "SIMULATION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["primary_metric"] == "RMSE"
    assert manifest["metric_direction"] == "minimize"
    assert {
        item["metric_direction"]
        for item in manifest["domain_asset_profile"]
        if item["stable_role"] not in {
            "error_analysis",
            "calibration_risk_coverage",
        }
    } == {"minimize"}

    engine = WorkflowEngine()
    main_rows = engine._simulation_result_rows(simulated / "main_comparison.csv")
    proposed = main_rows[-1]
    assert float(proposed["value"]) == min(float(row["value"]) for row in main_rows)
    assert {row["metric_direction"] for row in main_rows} == {"minimize"}

    run = _run(tmp_path, evidence_mode="synthetic_preview")
    engine._ensure_planned_results_analysis(run, "generic RMSE benchmark")
    analysis_path = tmp_path / "experiments" / "results" / "analysis.md"
    analysis = analysis_path.read_text(encoding="utf-8")
    assert "lower values are better" in analysis
    assert proposed["method"] in analysis
    assert "The primary endpoint is RMSE; lower values are better." in analysis
    assert "## Package completeness" not in analysis

    robustness = simulated / "robustness.csv"
    robustness.write_bytes(robustness.read_bytes() + b"\n")
    engine._ensure_planned_results_analysis(run, "generic RMSE benchmark")
    drifted = analysis_path.read_text(encoding="utf-8")
    assert "## Package completeness" in drifted
    assert "does not match its SHA-256 binding" in drifted
    assert "## Metric provenance and run identity" not in drifted


def test_explicit_metric_direction_overrides_name_heuristic() -> None:
    assert experiment_placeholder_service._metric_direction("RMSE") == "minimize"
    assert (
        experiment_placeholder_service._metric_direction("RMSE", "maximize")
        == "maximize"
    )


def test_downstream_planning_rejects_invalid_simulation_package_without_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def render_without_matplotlib(script: Path) -> tuple[bool, str]:
        script.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% migration test\n")
        script.with_suffix(".svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            encoding="utf-8",
        )
        script.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return True, ""

    monkeypatch.setattr(
        experiment_placeholder_service,
        "_render",
        render_without_matplotlib,
    )
    _project_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "legacy simulation package",
            evidence_mode="synthetic_preview",
            research_family="machine_learning",
            study_archetype="algorithm_benchmark",
        )
    )
    manifest_path = (
        tmp_path / "experiments" / "results" / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy["schema"] = 4
    legacy.pop("primary_metric", None)
    legacy.pop("metric_direction", None)
    for profile in legacy.get("domain_asset_profile") or []:
        profile.pop("metric_direction", None)
    manifest_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    engine = WorkflowEngine()
    run = _run(tmp_path, "ppt-only-legacy", "synthetic_preview")
    run.nodes = [WorkflowNode(id="ppt", name="Slides", skill="/paper-talk")]
    run.checkpoint_node_id = "ppt"
    protected = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="current bundle schema and renderer"):
        asyncio.run(
            engine._ensure_planned_result_templates(
                run,
                "legacy simulation package",
                force=False,
            )
        )
    assert all(path.read_bytes() == content for path, content in protected.items())
    assert manifest_path.read_bytes() == protected[manifest_path]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["schema"] == 4
    assert scientific_slide_service.qualified_synthetic_figures(tmp_path) == []


def test_old_renderer_is_rejected_without_regeneration_or_scientific_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_count = 0

    async def render_without_matplotlib(script: Path) -> tuple[bool, str]:
        nonlocal render_count
        render_count += 1
        script.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% renderer migration\n")
        script.with_suffix(".svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            encoding="utf-8",
        )
        script.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return True, ""

    monkeypatch.setattr(
        experiment_placeholder_service,
        "_render",
        render_without_matplotlib,
    )
    _project_contract(tmp_path)
    direction = "renderer migration benchmark"
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            direction,
            evidence_mode="synthetic_preview",
            research_family="machine_learning",
            study_archetype="algorithm_benchmark",
        )
    )
    assert render_count == 7

    manifest_path = (
        tmp_path / "experiments" / "results" / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic_before = simulation_manifest_semantic_hash(manifest)
    manifest["renderer_version"] = SIMULATION_RENDERER_VERSION - 1
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert simulation_manifest_semantic_hash(manifest) == semantic_before

    engine = WorkflowEngine()
    run = _run(tmp_path, "renderer-migration", "synthetic_preview")
    run.options.update({
        "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
    })
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="Unsupported simulation renderer version"):
        asyncio.run(engine._refresh_simulation_renderer_before_revalidation(run, direction))
    assert render_count == 7
    assert all(path.read_bytes() == content for path, content in before.items())
    unchanged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert unchanged["renderer_version"] == SIMULATION_RENDERER_VERSION - 1
    assert simulation_manifest_semantic_hash(unchanged) == semantic_before


def test_malformed_renderer_version_is_a_contract_issue_not_an_exception() -> None:
    issues = simulation_manifest_contract_issues({
        "schema": 5,
        "renderer_version": {"invalid": True},
    })

    assert f"renderer version is older than {SIMULATION_RENDERER_VERSION}" in issues


@pytest.mark.asyncio
async def test_no_experiment_results_revision_uses_platform_repair_not_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_contract(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        "# Planned Result Analysis (NOT EVIDENCE)\n\n"
        "Experiments were not run. The proposed method significantly outperforms baselines.\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    node = WorkflowNode(id="results", name="Results", skill="/analyze-results")
    run = _run(tmp_path, "planned-results-revision")
    run.nodes = [node]
    events: list[tuple[str, dict[str, Any]]] = []

    async def fail_if_model_called(*_args, **_kwargs) -> str:
        raise AssertionError("no-experiment results repair must not invoke a model")

    async def emit(_run, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_execute_node", fail_if_model_called)
    monkeypatch.setattr(engine, "_emit", emit)

    result = await engine._revise_node_from_gate(
        node=node,
        run=run,
        diagnostics={"issues": ["unsupported empirical wording"]},
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test direction",
        effort="balanced",
        assurance="submission",
        opts=run.options,
    )

    assert "deterministic planned-result analysis" in result
    assert any(name == "planned_results_platform_repair" for name, _ in events)
    report = analysis.read_text(encoding="utf-8")
    assert "To be tested:" in report
    assert "The claim would be rejected if" in report


@pytest.mark.asyncio
async def test_no_experiment_results_revision_loop_repairs_and_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_contract(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        "# Planned Result Analysis (NOT EVIDENCE)\n\n"
        "Experiments were not run. The proposed method significantly "
        "outperforms every baseline.\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    node = WorkflowNode(id="results", name="Results", skill="/analyze-results")
    run = _run(tmp_path, "planned-results-loop")
    run.nodes = [node]
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {
            "direction": "test direction",
            "effort": "balanced",
            "assurance": "submission",
            "options": run.options,
        },
    )
    revision_calls = 0

    async def prepare(
        _node,
        _run,
        result,
        *_args,
        **_kwargs,
    ) -> str:
        return result

    async def completed_specialists(**_kwargs) -> dict[str, Any]:
        # This unit test isolates the local repair/risk loop, not model-backed
        # specialist execution. Full-gate snapshot tests cover that boundary.
        return {"accepted": True}

    async def emit(*_args, **_kwargs) -> None:
        return None

    def acceptance(*_args, **_kwargs) -> dict[str, Any]:
        findings = node_risk_audit_service._audit_results(
            tmp_path,
            run.options,
        )
        blockers = [
            item for item in findings
            if item.get("severity") == "blocker"
        ]
        if blockers:
            return {
                "accepted": False,
                "reason": "node-specific research risk audit failed",
                "summary": str(blockers[0].get("plain_message") or ""),
                "details": {
                    "issues": [
                        str(item.get("plain_message") or item.get("message") or "")
                        for item in blockers
                    ],
                    "findings": blockers,
                },
            }
        return {
            "accepted": True,
            "verdict_id": "results:planned-repaired",
            "reviewer": "deterministic:test",
            "summary": "planned analysis accepted",
            "details": {},
        }

    original_revision = engine._revise_node_from_gate

    async def revise(**kwargs) -> str:
        nonlocal revision_calls
        revision_calls += 1
        return await original_revision(**kwargs)

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_execute_profile_specialists", completed_specialists)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="planned analysis",
        research_direction="test direction",
        effort="balanced",
        assurance="submission",
        opts=run.options,
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["accepted"] is True
    assert gate.get("waiting") is not True
    assert revision_calls == 1
    report = analysis.read_text(encoding="utf-8")
    assert "Hypothesis to be tested (PENDING):" in report
    assert "significantly outperforms every baseline" not in report
    revision = state.revision_state("results")
    assert revision.get("waiting") is not True


@pytest.mark.asyncio
async def test_results_specialist_transport_failure_does_not_rewrite_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_contract(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        "# Planned Result Analysis (NOT EVIDENCE)\n\nPending evidence.\n",
        encoding="utf-8",
    )
    original = analysis.read_text(encoding="utf-8")
    engine = WorkflowEngine()
    node = WorkflowNode(id="results", name="Results", skill="/analyze-results")
    run = _run(tmp_path, "planned-results-specialist-transport")
    run.nodes = [node]
    events: list[tuple[str, dict[str, Any]]] = []

    async def failed_specialist(**_kwargs) -> dict[str, Any]:
        return {
            "accepted": False,
            "error": "RuntimeError: OpenAI API error 502: upstream unavailable",
        }

    async def emit(_run, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_execute_profile_specialists", failed_specialist)
    monkeypatch.setattr(engine, "_emit", emit)

    with pytest.raises(RuntimeError, match="502"):
        await engine._revise_node_from_gate(
            node=node,
            run=run,
            diagnostics={
                "reason": "required research-profile specialist subnode failed",
                "issues": ["specialist subnode domain-validation is failed"],
            },
            round_number=1,
            cycle=1,
            user_feedback="",
            research_direction="test direction",
            effort="balanced",
            assurance="submission",
            opts=run.options,
        )

    assert analysis.read_text(encoding="utf-8") == original
    assert not any(name == "planned_results_platform_repair" for name, _ in events)


@pytest.mark.asyncio
async def test_gate_preparation_changes_stale_planned_analysis_from_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_contract(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        "# Planned Result Analysis (NOT EVIDENCE)\n\n"
        "Experiments were not run. A baseline outperforms the proposed method.\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    node = WorkflowNode(id="results", name="Results", skill="/analyze-results")
    run = _run(tmp_path, "planned-results-freshness")
    run.nodes = [node]
    node.artifact_baseline = engine._snapshot_node_artifacts(node, run)

    async def emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )

    await engine._prepare_node_for_gate(
        node,
        run,
        "",
        "test direction",
        "submission",
        run.options,
    )

    changed = engine._changed_nonempty_node_artifacts(node, run)
    assert analysis in changed
