from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from server.services.execution_provenance import execution_provenance_service
from server.services.scientific_assets import scientific_asset_service
from server.services.scientific_plotting import build_scientific_plot_script


def _record_runtime_artifact(root: Path) -> None:
    now = time.time()
    execution_provenance_service.record(
        root,
        "cross-domain-test",
        "Bash",
        {"command": "python run_study.py"},
        True,
        now - 2,
        now,
        "[exit code: 0]",
    )


def test_clinical_effect_parser_preserves_reported_interval_and_subgroup(
    tmp_path: Path,
) -> None:
    result_dir = tmp_path / "experiments" / "results"
    result_dir.mkdir(parents=True)
    path = result_dir / "clinical_effects.csv"
    rows = [
        {
            "status": "completed",
            "predictor": "Biomarker positive",
            "endpoint": "Overall survival",
            "hazard_ratio": "0.72",
            "ci_lower": "0.58",
            "ci_upper": "0.89",
            "subgroup": "External cohort",
            "p_value": "0.003",
            "unit": "ratio",
        },
        {
            "status": "completed",
            "predictor": "Biomarker negative",
            "endpoint": "Overall survival",
            "hazard_ratio": "1.08",
            "ci_lower": "0.91",
            "ci_upper": "1.29",
            "subgroup": "External cohort",
            "p_value": "0.38",
            "unit": "ratio",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _record_runtime_artifact(tmp_path)

    records = scientific_asset_service.collect_records(tmp_path)

    assert len(records) == 2
    first = next(item for item in records if item.method == "Biomarker positive")
    assert first.metric == "Overall survival (hazard ratio)"
    assert first.value == 0.72
    assert first.ci_low == 0.58
    assert first.ci_high == 0.89
    assert first.condition_name == "subgroup"
    assert first.condition_value == "External cohort"
    assert first.role == "robustness"

    aggregated = scientific_asset_service._aggregate(records)
    positive = next(item for item in aggregated if item["method"] == "Biomarker positive")
    assert positive["ci95_low"] == "0.58"
    assert positive["ci95_high"] == "0.89"
    assert positive["ci_method"] == "reported"
    assert positive["condition_value"] == "External cohort"


def test_plot_builder_dispatches_domain_encoding_without_inventing_columns() -> None:
    script = build_scientific_plot_script(
        {
            "data_path": "experiments/results/aggregates/dose.csv",
            "metric": "Response (mmol/L)",
            "publication_labels": [{
                "schema": 1, "id": "dose.response", "kind": "metric",
                "display_text": "Response (mmol/L)",
            }],
            "recommended_plot_type": "dose_response",
            "scientific_question": "How does response change with dose?",
            "evidence_status": "executed",
        },
        {
            "family": "experimental_natural_science",
            "study_archetype": "controlled_experiment",
            "canvas": {"target_font_pt": 7},
            "palette": {"blue": "#0072B2", "orange": "#E69F00"},
        },
        idea="Registered dose-response study",
    )

    compile(script, "dose_response.py", "exec")
    assert "PLOT_TYPE = 'dose_response'" in script
    assert "def curve_plot" in script
    assert "def interval_plot" in script
    assert "Registered condition" in script
    assert "seaborn" not in script


def test_theory_plot_uses_theory_specific_typography_contract() -> None:
    script = build_scientific_plot_script(
        {
            "data_path": "experiments/results/aggregates/bounds.csv",
            "metric": "Upper bound",
            "publication_labels": [{
                "schema": 1, "id": "theory.bound", "kind": "metric",
                "display_text": "Upper bound",
            }],
            "recommended_plot_type": "bound_comparison",
        },
        {
            "family": "theoretical_formal",
            "study_archetype": "formal_theory",
            "fonts": ["STIX Two Text", "DejaVu Serif", "serif"],
            "canvas": {"target_font_pt": 8},
            "palette": {"blue": "#0072B2"},
        },
    )

    assert '"font.family": PUBLICATION_STYLE["font_family"]' in script
    assert "'font_family': 'DejaVu Serif'" in script


def test_qualitative_runtime_evidence_builds_traceable_matrix_and_summary(
    tmp_path: Path,
) -> None:
    idea = {
        "schema": 2, "status": "accepted", "title": "Trust calibration study",
        "problem_statement": "Teams calibrate trust under contradictory advice.",
        "hypothesis": "Negative cases change verification routines.",
        "claims": [{"id": "C1", "statement": "Internal claim", "publication_statement": "Negative cases reshape verification routines."}],
        "mechanisms": [{"id": "M1", "name": "Internal coding", "description": "Triangulated coding", "publication_name": "Triangulated negative-case analysis", "publication_description": "Compares supporting and contradictory evidence across cases.", "publication_evaluation": "Cross-case negative-case coverage and triangulation.", "required": True}],
        "falsification_conditions": ["No cross-case difference."],
        "publication": {"language": "en", "title": "Trust Calibration Under Contradictory Advice", "method_name": "Triangulated trust framework", "contribution_type": "qualitative_framework", "comparator_names": ["Supporting cases", "Negative cases"]},
    }
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas/SELECTED_IDEA.json").write_text(json.dumps(idea), encoding="utf-8")
    (tmp_path / 'experiments').mkdir()
    (tmp_path / 'experiments/METHOD_CONTRACT.json').write_text(json.dumps({
        'scientific_scene': {'schema': 1, 'objects': [
            {'id': 'cases', 'kind': 'population', 'label': 'Supporting and negative cases', 'source_path': 'ideas/SELECTED_IDEA.json'},
            {'id': 'coding', 'kind': 'operation', 'label': 'Triangulated negative-case analysis', 'source_path': 'ideas/SELECTED_IDEA.json'},
        ], 'relations': [{'from': 'cases', 'to': 'coding', 'kind': 'data'}]},
    }), encoding='utf-8')
    result_dir = tmp_path / "experiments" / "results"
    result_dir.mkdir(parents=True)
    path = result_dir / "coded_evidence.csv"
    rows = [
        {
            "status": "completed",
            "theme": "Trust calibration",
            "case": "Case A",
            "excerpt": "Participants compared system advice with prior experience.",
            "source_id": "INT-A-14",
            "polarity": "supporting",
            "coder": "analyst-1",
            "source_type": "interview",
        },
        {
            "status": "completed",
            "theme": "Trust calibration",
            "case": "Case B",
            "excerpt": "A contradictory recommendation reduced reliance.",
            "source_id": "OBS-B-03",
            "polarity": "negative",
            "coder": "analyst-2",
            "source_type": "observation",
        },
        {
            "status": "completed",
            "theme": "Workflow adaptation",
            "case": "Case B",
            "excerpt": "The team changed its verification routine.",
            "source_id": "OBS-B-09",
            "polarity": "supporting",
            "coder": "analyst-2",
            "source_type": "observation",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _record_runtime_artifact(tmp_path)

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=True,
        direction="Interview study with thematic coding and negative cases",
        research_family="qualitative_humanities",
        study_archetype="qualitative_mixed",
        target_venue="Qualitative Research",
    )

    assert plan["evidence_mode"] == "executed"
    assert plan["submission_eligible"] is True
    assert plan["qualitative_record_count"] == 3
    main = next(item for item in plan["assets"] if item["id"] == "main_comparison")
    assert main["recommended_plot_type"] in {"theme_map", "evidence_matrix"}
    assert main["recommended_backend"] == "matplotlib"
    assert main["recommended_skill"] == "paper-figure"
    evaluation = next(
        item for item in plan["assets"] if item["id"] == "evaluation_design"
    )
    method = next(
        item for item in plan["assets"] if item["id"] == "method_architecture"
    )
    assert method["figure_type"] == "coding_interpretation_pipeline"
    assert method["scene_contract"]["maximum_primary_nodes"] == 7
    assert evaluation["figure_type"] == "sampling_coding_triangulation_flow"
    assert evaluation["narrative_level"] == "study_protocol"
    assert {item["id"] for item in plan["figure_portfolio"]} == {
        "method_architecture", "evaluation_design",
    }
    assert evaluation["recommended_backend"] == "rich_svg"
    assert evaluation["recommended_skill"] == "deterministic-figure-template"
    assert evaluation["figure_nature"] == "standard_protocol"
    assert evaluation["production_strategy"] == "deterministic_template"
    assert evaluation["producer_kind"] == "deterministic"
    assert method["production_strategy"] == "deterministic_architecture"
    assert method["recommended_backend"] == "figurespec"
    assert method["recommended_skill"] == "figure-spec"
    assert main["production_strategy"] == "deterministic_plot"
    assert main["producer_kind"] == "deterministic"
    matrix_path = tmp_path / main["data_path"]
    assert matrix_path.is_file()
    matrix_rows = list(csv.DictReader(
        matrix_path.open("r", encoding="utf-8-sig", newline="")
    ))
    assert {item["theme"] for item in matrix_rows} == {
        "Trust calibration",
        "Workflow adaptation",
    }
    summary = list(csv.DictReader(
        (tmp_path / "experiments" / "results" / "aggregates" / "main_comparison.csv").open(
            "r",
            encoding="utf-8-sig",
            newline="",
        )
    ))
    trust = next(item for item in summary if item["theme"] == "Trust calibration")
    assert trust["negative_case_count"] == "1"
    assert trust["case_count"] == "2"

    persisted = json.loads(
        (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["publication_style"]["family"] == "qualitative_humanities"
