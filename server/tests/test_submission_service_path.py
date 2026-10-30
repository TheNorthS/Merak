from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from server.services.figure_artifacts import figure_artifact_registry
from server.services.paper_artifacts import paper_artifact_builder
from server.services.paper_compiler import paper_compiler
from server.services.remote_experiment_runtime import (
    ExperimentRuntime,
    RuntimeSpec,
)
from server.services.scientific_assets import scientific_asset_service
from server.services.scientific_evidence import scientific_evidence_service
from server.services.workflow_readiness import (
    SUBMISSION_PHASES,
    workflow_readiness_service,
)
from server.workflows.review_audit import (
    AUDIT_LAYER_SKILLS,
    AuditResult,
    ReviewRound,
    ReviewState,
    Verdict,
    audit_chain,
    cross_model_reviewer,
    review_source_bundle,
)
from server.workflows.run_state import RunState


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_research_contracts(root: Path) -> None:
    _write_json(root / "ideas" / "SELECTED_IDEA.json", {
        "schema": 2,
        "status": "accepted",
        "title": "Runtime-owned transfer calibration",
        "hypothesis": (
            "The calibrated method improves held-out accuracy over the matched "
            "baseline under the registered split."
        ),
        "claims": [{
            "id": "C1",
            "statement": "The calibrated method improves held-out accuracy.",
            "publication_statement": "The calibrated method improves held-out accuracy under the registered comparison.",
        }],
        "mechanisms": [{
            "id": "M1",
            "name": "Calibration mechanism",
            "description": "A registered calibration layer applied before evaluation.",
            "publication_name": "Calibration mechanism",
            "publication_description": "Applies the registered calibration layer before held-out evaluation.",
            "publication_evaluation": "Compare held-out accuracy with the matched baseline under the registered split.",
        }],
        "falsification_conditions": [
            "Reject C1 when the matched baseline is not lower on the held-out split."
        ],
        "publication": {"language": "en", "title": "Runtime-Owned Transfer Calibration",
                        "method_name": "Registered calibration", "contribution_type": "objective_mechanism",
                        "comparator_names": ["Proposed", "Matched baseline"]},
    })
    _write_json(root / "experiments" / "METHOD_CONTRACT.json", {
        "schema": 2,
        "scientific_scene": {"schema": 1, "objects": [
            {"id": "calibration_operation", "kind": "operation", "label": "Calibration mechanism",
             "source_path": "ideas/SELECTED_IDEA.json"},
            {"id": "heldout_measurement", "kind": "measurement", "label": "Held-out accuracy measurement",
             "source_path": "experiments/METHOD_CONTRACT.json"},
        ], "relations": [{"from": "calibration_operation", "to": "heldout_measurement", "kind": "data"}]},
        "claim_evidence_plan": [{
            "idea_claim_id": "C1",
            "outcomes": ["Compare held-out accuracy with the matched baseline."],
            "failure_conditions": ["The confidence interval includes no improvement."],
            "evidence_status": "executed",
        }],
    })
    _write_json(root / "experiments" / "RUN_SPEC.json", {
        "stage": "evaluation",
        "primary_metric": "accuracy",
        "seeds": [1, 2, 3],
    })
    (root / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nCompare Proposed and Matched baseline across three seeds.\n",
        encoding="utf-8",
    )
    (root / "literature").mkdir(parents=True, exist_ok=True)
    (root / "literature" / "references.bib").write_text(
        "@article{fixture2026, title={Runtime-owned evidence}, "
        "author={Fixture, A.}, journal={Test Journal}, year={2026}}\n",
        encoding="utf-8",
    )
    (root / "literature" / "survey.md").write_text(
        "# Literature Survey\n\nThe registered comparison addresses a bounded gap.\n",
        encoding="utf-8",
    )


def _write_runtime_script(root: Path) -> Path:
    config = root / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "experiment:\n  primary_metric: accuracy\n  seeds: [1, 2, 3]\n",
        encoding="utf-8",
    )
    script = root / "experiments" / "src" / "emit_runtime_evidence.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "from pathlib import Path\n"
        "import csv, json\n"
        "root = Path(__file__).resolve().parents[2]\n"
        "results = root / 'experiments' / 'results'\n"
        "logs = root / 'experiments' / 'logs'\n"
        "results.mkdir(parents=True, exist_ok=True)\n"
        "logs.mkdir(parents=True, exist_ok=True)\n"
        "rows = [\n"
        "    ('Proposed', 1, 0.82), ('Proposed', 2, 0.84), ('Proposed', 3, 0.83),\n"
        "    ('Matched baseline', 1, 0.74), ('Matched baseline', 2, 0.76),\n"
        "    ('Matched baseline', 3, 0.75),\n"
        "]\n"
        "with (results / 'main_metrics.csv').open('w', encoding='utf-8', newline='') as handle:\n"
        "    writer = csv.writer(handle)\n"
        "    writer.writerow(['status', 'method', 'seed', 'split', 'metric', 'value', 'ci95_low', 'ci95_high'])\n"
        "    for method, seed, value in rows:\n"
        "        writer.writerow(['completed', method, seed, 'test', 'accuracy', value, value - 0.01, value + 0.01])\n"
        "with (results / 'predictions.csv').open('w', encoding='utf-8', newline='') as handle:\n"
        "    writer = csv.writer(handle)\n"
        "    writer.writerow(['sample_id', 'target', 'prediction', 'seed', 'split'])\n"
        "    writer.writerows([['s1', 1, 1, 1, 'test'], ['s2', 0, 0, 1, 'test']])\n"
        "(logs / 'training.jsonl').write_text(\n"
        "    '\\n'.join(json.dumps({'step': step, 'train/loss': loss}) for step, loss in [(1, 0.9), (2, 0.6), (3, 0.4)]) + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "for step, loss in [(1, 0.9), (2, 0.6), (3, 0.4)]:\n"
        "    print(json.dumps({'step': step, 'train/loss': loss}), flush=True)\n",
        encoding="utf-8",
    )
    return script


def _record_scientific_figure(root: Path, plan: dict) -> None:
    """Fixture figure bytes isolate readiness attestation, not pixel-quality acceptance."""
    figure_assets = [
        item
        for item in plan.get("assets", [])
        if isinstance(item, dict) and item.get("kind") == "figure"
    ]
    selected = next(
        (
            item
            for item in figure_assets
            if item.get("scientific_role") in {"result", "main_comparison"}
        ),
        figure_assets[0] if figure_assets else {
            "id": "main_comparison",
            "scientific_role": "result",
            "caption": "Held-out accuracy across registered methods.",
        },
    )
    output = root / "figures" / "plots" / f"{selected['id']}.png"
    source = root / "figures" / "plots" / f"{selected['id']}.py"
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color=(240, 244, 248)).save(
        output,
        format="PNG",
    )
    with Image.open(output) as image:
        image.verify()
    source.write_text(
        "# Editable source for the runtime-backed comparison figure.\n",
        encoding="utf-8",
    )
    figure_artifact_registry.record(
        output_dir=root / "figures",
        figure_type="python",
        description=str(selected.get("caption") or "Runtime-backed comparison"),
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": str(selected.get("id") or "main_comparison"),
            "scientific_role": "result",
            "evidence_status": "executed",
            "manuscript_eligible": True,
            "paper_selected": True,
            "source_data": ["experiments/results/main_metrics.csv"],
            "provenance_kind": "runtime_owned",
        },
    )


def test_submission_asset_planning_rejects_missing_publication_without_rewriting_inputs(tmp_path: Path) -> None:
    _write_research_contracts(tmp_path)
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    payload = json.loads(selected.read_text(encoding="utf-8"))
    payload.pop("publication")
    _write_json(selected, payload)
    before = {path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="publication contribution_type is required"):
        scientific_asset_service.build_plan(tmp_path, experiment_requested=True, requested_evidence_mode="executed",
                                            direction="Runtime-owned transfer calibration", target_venue="ICLR")
    assert before == {path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in tmp_path.rglob("*") if path.is_file()}


def _write_paper(root: Path, figure_id: str) -> None:
    paper = root / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{graphicx}\n"
        "\\title{Runtime-owned Transfer Calibration}\n"
        "\\author{MERAK Integration Fixture}\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\begin{abstract}\n"
        "We evaluate a registered calibration mechanism using runtime-owned "
        "per-seed measurements and a matched baseline.\n"
        "\\end{abstract}\n"
        "\\section{Introduction} The study tests a bounded transfer claim.\n"
        "\\section{Method} The calibration layer is fixed before evaluation.\n"
        "\\section{Experimental protocol} Three seeds use the same held-out split.\n"
        "\\section{Results} Runtime-owned records show the registered comparison.\n"
        "\\begin{figure}[h]\\centering\n"
        f"\\includegraphics[width=0.25\\linewidth]{{../figures/plots/{figure_id}.png}}\n"
        "\\caption{Runtime-backed main comparison.}\\end{figure}\n"
        "\\section{Limitations} This fixture proves service integration, not a domain claim.\n"
        "\\section{Conclusion} All reported values remain bound to runtime artifacts.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_runtime_owned_services_reach_submission_readiness(
    tmp_path: Path,
) -> None:
    if shutil.which("latexmk") is None:
        pytest.skip("latexmk is required for the real compiler service path")

    run_id = "service-path-submission"
    _write_research_contracts(tmp_path)
    script = _write_runtime_script(tmp_path)
    runtime = ExperimentRuntime()
    outcome = await runtime.run(RuntimeSpec(
        run_id="managed-local-evidence",
        project_path=str(tmp_path),
        command=subprocess.list2cmdline([
            sys.executable,
            "-u",
            str(script.relative_to(tmp_path)),
        ]),
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    ))
    assert outcome.status == "completed"

    manifest = json.loads(Path(outcome.manifest_path).read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert "experiments/results/main_metrics.csv" in manifest["result_artifacts"]
    assert "experiments/results/predictions.csv" in manifest["result_artifacts"]
    assert "experiments/configs/main.yaml" in manifest["config_hashes"]

    evidence_ok, evidence_issues, evidence_details = (
        scientific_evidence_service.validate_executed_metrics(tmp_path)
    )
    assert evidence_ok, evidence_issues
    assert "experiments/results/main_metrics.csv" in evidence_details["proven_sources"]

    asset_plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=True,
        requested_evidence_mode="executed",
        direction="Runtime-owned transfer calibration",
        target_venue="ICLR",
        research_family="machine_learning",
        study_archetype="algorithm_benchmark",
    )
    assert asset_plan["evidence_mode"] == "executed"
    assert asset_plan["submission_eligible"] is True
    _record_scientific_figure(tmp_path, asset_plan)
    figure_manifest = figure_artifact_registry.load(tmp_path / "figures")
    figure_id = str(figure_manifest["figures"][0]["id"])

    _write_paper(tmp_path, figure_id)
    paper_evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Runtime-owned transfer calibration",
    )
    assert paper_evidence.submission_eligible is True
    _write_json(tmp_path / "paper" / "PAPER_BUILD.json", {
        "schema": 1,
        "evidence_mode": "executed",
        "submission_eligible": True,
        "manuscript_class": "submission_candidate",
    })
    compile_result = await paper_compiler.compile(str(tmp_path / "paper"))
    assert compile_result.success, compile_result.errors
    assert paper_compiler.refresh_build_record(
        tmp_path / "paper",
        "PAPER_BUILD.json",
        "main.pdf",
        pages=compile_result.pages,
        compile_time_ms=compile_result.compile_time_ms,
        warning_count=len(compile_result.warnings),
    )

    original_snapshot = tmp_path / "paper" / "main_round0_original.pdf"
    final_snapshot = tmp_path / "paper" / "main_round1.pdf"
    shutil.copyfile(tmp_path / "paper" / "main.pdf", original_snapshot)
    shutil.copyfile(tmp_path / "paper" / "main.pdf", final_snapshot)
    layout_report = tmp_path / "review-stage" / "pdf-layout" / "main_round1.json"
    _write_json(layout_report, {
        "schema": 1,
        "pdf_path": "paper/main_round1.pdf",
        "page_count": compile_result.pages,
        "renderer": "integration-test-renderer",
        "pages": [{"page": 1, "possible_layout_findings": []}],
    })
    review_hash, _ = review_source_bundle(tmp_path)
    visual_review = {
        "pdf_path": "paper/main_round1.pdf",
        "figure_quality": "All rendered figures are legible at paper scale.",
        "caption_alignment": "Captions align with the inspected figures.",
        "page_layout": "No clipping, overlap, or broken page flow is visible.",
        "table_formatting": "Tables are aligned and readable.",
        "visual_consistency": "Typography and visual encodings are consistent.",
    }

    review_state = ReviewState(
        run_id=run_id,
        rounds=[ReviewRound(
            round_number=1,
            score=8.0,
            verdict="ready",
            strengths=["Runtime provenance and claim scope are explicit."],
            weaknesses=["No unresolved visual blocker remained after inspection."],
            action_items=["Retain the inspected layout in the final snapshot."],
            pdf_snapshot="paper/main_round1.pdf",
            visual_review=visual_review,
        )],
        current_round=1,
        max_rounds=1,
        final_score=8.0,
        final_verdict="ready",
        is_complete=True,
        threshold_met=True,
        bounded_complete=True,
        executor_provider="writer",
        reviewer_provider="reviewer",
        executor_model="openai/gpt-writer",
        reviewer_model="openai/gpt-reviewer",
        evidence_mode="executed",
        publication_ready=True,
        policy_loaded=True,
        phase="completed",
        reviewer_session_ids=["review-session"],
        executor_session_ids=["writer-session"],
        pdf_snapshots=[
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
    )
    cross_model_reviewer._save_state(review_state, str(tmp_path))

    audit_results = [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=Verdict.PASS,
            summary="Runtime-backed audit passed.",
            method="model",
            skill_name=AUDIT_LAYER_SKILLS[layer],
            session_id=f"audit-session-{layer}",
            policy_loaded=True,
            model_name="openai/gpt-reviewer",
        )
        for layer in range(1, 6)
    ]
    audit_chain._save_results(
        audit_results,
        str(tmp_path),
        "executed",
        run_id=run_id,
    )

    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [
            {"id": phase, "name": phase, "skill": f"/{phase}"}
            for phase in SUBMISSION_PHASES
        ],
        {
            "direction": "Runtime-owned transfer calibration",
            "effort": "balanced",
            "assurance": "submission",
            "options": {
                "run_experiment": True,
                "non_experiment_evidence_mode": "executed",
            },
        },
    )
    for phase in SUBMISSION_PHASES:
        run_state.set_status(phase, "done")
        run_state.accept(phase, f"service:{phase}", "integration:service-path")

    report = workflow_readiness_service.assess(
        tmp_path,
        run_state.load(),
        persist=False,
    )

    assert report["execution_completed"] is True
    assert report["submission_ready"] is True, report["submission_blockers"]
    assert report["completion_class"] == "submission_ready"
    assert set(report["attestations"]) == {
        "figures", "paper", "review", "audit", "simulation",
    }
    assert report["attestations"]["simulation"] == {
        "applicable": False,
        "valid": True,
        "issue_count": 0,
    }
    assert all(
        attestation["valid"] is True
        for attestation in report["attestations"].values()
    )
