"""Cross-domain publication semantics, visual scale, and table/PDF gates."""

from __future__ import annotations

import json
import ast
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from server.services.figure_print_policy import svg_print_contract_issues
from server.services.method_contract import method_contract_service
from server.services.paper_pdf_quality import inspect_compiled_paper, pdf_layout_issues, validate_persisted_pdf_quality
from server.services.scientific_figure_prompt import figure_authoring_prompt
from server.services.publication_semantics import (
    CONTRIBUTION_TYPES,
    validate_publication_semantics,
)
from server.services.publication_table_policy import publication_table_issues
from server.services.scientific_asset_portfolio import (
    complexity_budget,
    figure_portfolio,
    method_story,
)
from server.services.scientific_asset_builders import design_assets
from server.services.evidence_asset_portfolio import selected_evidence_asset_ids
from server.services.simulation_table_projection import _main_table, _select_manuscript_tables
from server.services.scientific_scene import plan_scientific_layout, validate_scientific_scene
from server.services.semantic_table import ScientificTableSpec, TableColumn, compile_scientific_table
from server.services.publication_pdf_fonts import minimum_readable_font_pt
from server.services.simulation_comparison_plots import _bar_script
from server.services.scientific_scene_geometry import solve_scientific_panel
from server.services.paper_layout_attribution import layout_repair_findings


def _idea(contribution: str = "objective_mechanism") -> dict:
    return {
        "schema": 2, "status": "accepted", "title": "Internal title",
        "problem_statement": "A concrete research problem.",
        "hypothesis": "A falsifiable scientific hypothesis.",
        "claims": [{
            "id": "C1", "statement": "Internal measurable claim",
            "publication_statement": "The named mechanism changes the primary endpoint.",
        }],
        "mechanisms": [{
            "id": "M1", "name": "Internal mechanism",
            "description": "Internal implementation description", "required": True,
            "publication_name": "Selective invariance objective",
            "publication_description": "Suppresses measured nuisance while preserving task information.",
            "publication_evaluation": "Matched removal comparison on the primary endpoint.",
        }],
        "falsification_conditions": ["No matched improvement."],
        "publication": {
            "language": "en", "title": "Public title", "method_name": "Method X",
            "contribution_type": contribution,
            "comparator_names": ["Method X", "Matched control"],
        },
    }


@pytest.mark.parametrize("contribution", sorted(CONTRIBUTION_TYPES))
def test_every_contribution_type_selects_a_question_driven_story(contribution: str) -> None:
    payload = _idea(contribution)
    assert validate_publication_semantics(payload) == []
    story = method_story(payload["publication"])
    assert story["contribution_type"] == contribution
    assert story["scientific_question"].endswith("?")
    assert story["visual_grammar"]
    assert [item["asset_id"] for item in story["figure_portfolio"]] == [
        "method_architecture", "evaluation_design",
    ]
    assert story["maximum_primary_nodes"] <= 12
    assert story["minimum_placed_font_pt"] >= 8
    assert story["preferred_backend"] == (
        "rich_svg" if contribution == "experimental_protocol" else "figurespec"
    )
    evidence_assets = selected_evidence_asset_ids(contribution)
    assert "synthetic_preview_main_comparison" in evidence_assets
    assert 3 <= len(evidence_assets) <= 4


@pytest.mark.parametrize(
    ("contribution", "expected_types"),
    (
        ("model_architecture", {"method_architecture", "matched_model_evaluation"}),
        ("dataset_benchmark", {"benchmark_landscape", "benchmark_comparison_protocol"}),
        ("clinical_biological_mechanism", {"cohort_specimen_mechanism", "endpoint_and_external_validation"}),
        ("system_architecture", {"component_dataflow", "deployment_testbed_protocol"}),
        ("theory_proof", {"proof_dependency", "verification_and_counterexample_design"}),
        ("qualitative_framework", {"coding_interpretation_pipeline", "triangulation_and_negative_case_audit"}),
    ),
)
def test_contribution_selects_role_separated_figure_portfolio(
    contribution: str, expected_types: set[str],
) -> None:
    portfolio = figure_portfolio(_idea(contribution)["publication"])
    by_id = {item["asset_id"]: item for item in portfolio}

    assert set(by_id) == {"method_architecture", "evaluation_design"}
    assert expected_types.issubset({item["figure_type"] for item in portfolio})
    assert by_id["method_architecture"]["narrative_level"] == "method_overview"
    assert by_id["evaluation_design"]["narrative_level"] == "study_protocol"
    expected_primary = (
        "deterministic_template"
        if contribution == "experimental_protocol"
        else "deterministic_architecture"
    )
    assert by_id["method_architecture"]["production_strategy"] == expected_primary
    assert by_id["method_architecture"]["composition_owner"] == "runtime"
    assert by_id["method_architecture"]["full_svg_authority"] is False
    assert by_id["evaluation_design"]["production_strategy"] == "deterministic_template"
    assert by_id["evaluation_design"]["producer_kind"] == "deterministic"
    assert all(item["content_boundary"] for item in portfolio)
    assert all(
        item["complexity_budget"]["maximum_scientific_questions"] == 1
        and item["complexity_budget"]["maximum_primary_objects"] <= 8
        and item["complexity_budget"]["maximum_visible_labels"] <= 12
        for item in portfolio
    )


def test_explicit_detail_mandate_adds_one_deterministic_asset() -> None:
    publication = _idea("model_architecture")["publication"]
    publication["required_figure_assets"] = ["core_mechanism"]
    portfolio = figure_portfolio(publication)

    assert [item["asset_id"] for item in portfolio] == [
        "method_architecture", "core_mechanism", "evaluation_design",
    ]
    assert portfolio[1]["required_if"] == "explicit_contract"
    assert portfolio[1]["production_strategy"] == "deterministic_architecture"


def _method_portfolio_context(object_count: int) -> dict:
    from server.services.research_contract_versions import SCIENTIFIC_SCENE_SCHEMA

    objects = [{
        "id": f"stage_{index}",
        "kind": "input" if index == 0 else "output" if index == object_count - 1 else "operation",
        "label": f"Stage {index}",
        "source_path": "ideas/SELECTED_IDEA.json",
    } for index in range(object_count)]
    scene = {
        "schema": SCIENTIFIC_SCENE_SCHEMA,
        "objects": objects,
        "relations": [{
            "from": f"stage_{index}", "to": f"stage_{index + 1}", "kind": "data",
        } for index in range(object_count - 1)],
    }
    return {
        "publication": _idea("model_architecture")["publication"],
        "method_contract": {"scientific_scene": scene},
        "mechanisms": [
            {"id": "M1", "name": "Temporal path"},
            {"id": "M2", "name": "Channel path"},
        ],
        "claims": [{"id": "C1", "statement": "Matched gain"}],
        "source_artifacts": ["ideas/SELECTED_IDEA.json"],
    }


def test_two_mechanisms_inside_budget_do_not_force_second_model_figure() -> None:
    context = _method_portfolio_context(6)
    assets = design_assets(context, {}, True)

    assert [item["id"] for item in assets if item["kind"] == "figure"] == [
        "method_architecture", "evaluation_design",
    ]
    assert assets[0]["layout_plan"]["split_required"] is False


def test_method_overflow_with_internal_relation_adds_focused_detail() -> None:
    context = _method_portfolio_context(10)
    assets = design_assets(context, {}, True)

    assert [item["id"] for item in assets if item["kind"] == "figure"] == [
        "method_architecture", "core_mechanism", "evaluation_design",
    ]
    detail = assets[1]
    assert detail["required"] is True
    assert detail["scene_contract"]["required_if"] == "method_overview_overflow"
    assert detail["layout_plan"]["split_required"] is True


def test_overflow_without_distinct_internal_relation_keeps_two_figures() -> None:
    context = _method_portfolio_context(10)
    for item in context["method_contract"]["scientific_scene"]["objects"]:
        item["kind"] = "input"
    assets = design_assets(context, {}, True)

    assert assets[0]["layout_plan"]["split_required"] is True
    assert [item["id"] for item in assets if item["kind"] == "figure"] == [
        "method_architecture", "evaluation_design",
    ]


def test_method_contract_can_explicitly_require_detail_without_overflow() -> None:
    context = _method_portfolio_context(6)
    context["method_contract"]["required_figure_assets"] = ["core_mechanism"]
    assets = design_assets(context, {}, True)

    assert [item["id"] for item in assets if item["kind"] == "figure"] == [
        "method_architecture", "core_mechanism", "evaluation_design",
    ]
    assert assets[1]["scene_contract"]["required_if"] == "explicit_contract"


def test_explicit_detail_without_named_mechanism_fails_at_producer() -> None:
    context = _method_portfolio_context(6)
    context["mechanisms"] = []
    context["method_contract"]["required_figure_assets"] = ["core_mechanism"]

    with pytest.raises(ValueError, match="without a named mechanism"):
        design_assets(context, {}, True)


def test_study_archetype_specializes_evaluation_without_changing_stable_id() -> None:
    portfolio = figure_portfolio(
        _idea("clinical_biological_mechanism")["publication"],
        research_family="clinical_biomedical",
        study_archetype="intervention_trial",
    )
    evaluation = next(
        item for item in portfolio if item["asset_id"] == "evaluation_design"
    )

    assert evaluation["figure_type"] == "allocation_participant_endpoint_flow"
    assert evaluation["research_family"] == "clinical_biomedical"
    assert evaluation["study_archetype"] == "intervention_trial"
    assert complexity_budget("clinical_biological_mechanism")[
        "maximum_primary_objects"
    ] == 7


def test_selected_idea_requires_noncompatible_publication_schema(tmp_path: Path) -> None:
    idea = _idea()
    path = tmp_path / "ideas/SELECTED_IDEA.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(idea), encoding="utf-8")
    (tmp_path / "ideas/novelty_report.md").write_text("Internal title", encoding="utf-8")
    accepted, issues, _ = method_contract_service.validate_selected_idea(tmp_path)
    assert accepted is True
    assert issues == []
    idea["schema"] = 1
    path.write_text(json.dumps(idea), encoding="utf-8")
    accepted, issues, _ = method_contract_service.validate_selected_idea(tmp_path)
    assert accepted is False
    assert "current schema=2" in " ".join(issues)


def test_svg_gate_uses_placed_size_language_and_scene_complexity() -> None:
    svg = (
        '<svg viewBox="0 0 1800 900"><style>.small{font-size:11px}</style>'
        '<text class="small">Tiny English</text><text class="small">中文混排</text>'
        + ''.join(f'<g id="g{i}" data-role="primary"><circle r="4"/></g>' for i in range(9))
        + '</svg>'
    )
    issues = svg_print_contract_issues(svg, ET.fromstring(svg), {
        "publication_language": "en",
        "scene_contract": {
            "minimum_placed_font_pt": 8, "maximum_primary_nodes": 8,
            "target_width_fraction": 1,
        },
    })
    assert any("below 8.0 pt" in issue for issue in issues)
    assert any("mixed CJK" in issue for issue in issues)
    assert any("9 primary visual groups" in issue for issue in issues)


def test_model_svg_print_floor_rejects_css_shorthand_without_mutating_artwork() -> None:
    svg = (
        '<svg viewBox="0 0 1800 900"><style>.body{font:14px Arial}</style>'
        '<text class="body">Mechanism node</text></svg>'
    )
    issues = svg_print_contract_issues(
        svg, ET.fromstring(svg),
        {"scene_contract": {"minimum_placed_font_pt": 8, "target_width_fraction": 1}},
    )
    assert any("below 8.0 pt" in issue for issue in issues)


def test_publication_table_policy_rejects_template_language_and_one_row(tmp_path: Path) -> None:
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "bad.tex").write_text(
        r"\begin{tabular}{ll}\midrule registered\_factor\_1 & Full Method \\ \bottomrule\end{tabular}",
        encoding="utf-8",
    )
    issues = publication_table_issues(tmp_path)
    assert any("placeholder" in issue for issue in issues)
    assert any("one-row" in issue for issue in issues)


def test_pdf_layout_gate_blocks_tiny_text_overlap_and_internal_blank_page() -> None:
    issues = pdf_layout_issues({
        "pages": [
            {"page": 1, "visible_text_chars": 800, "minimum_font_pt": 6.5,
             "possible_layout_findings": ["2 possible overlapping text-block pair(s)"]},
            {"page": 2, "visible_text_chars": 0, "minimum_font_pt": 0,
             "possible_layout_findings": ["page appears blank or nearly blank"]},
            {"page": 3, "visible_text_chars": 300, "minimum_font_pt": 9,
             "possible_layout_findings": []},
        ],
    })
    assert any("below 8.0 pt" in issue for issue in issues)
    assert any("overlapping" in issue for issue in issues)
    assert any("page 2" in issue and "blank" in issue for issue in issues)


def test_simulation_keeps_complete_evidence_but_selects_contribution_tables() -> None:
    blocks = "\n".join(
        rf"\begin{{table*}}\label{{{label}}}\end{{table*}}"
        for label in (
            "tab:preview-main-results", "tab:preview-ablation",
            "tab:preview-robustness-calibration", "tab:preview-calibration",
            "tab:preview-efficiency", "tab:preview-error-analysis",
            "tab:paired-reversals", "tab:claim-evidence",
        )
    )
    profile = {
        "contribution_type": "objective_mechanism",
        "assets": {
            "main": {"table_label": "tab:preview-main-results"},
            "sensitivity": {"table_label": "tab:preview-ablation"},
            "robustness": {"table_label": "tab:preview-robustness-calibration"},
            "coverage": {"table_label": "tab:preview-calibration"},
            "burden": {"table_label": "tab:preview-efficiency"},
            "case_analysis": {"table_label": "tab:preview-error-analysis"},
        },
    }
    selected = _select_manuscript_tables(blocks, profile)
    assert "tab:preview-main-results" in selected
    assert "tab:preview-ablation" in selected
    assert "tab:preview-robustness-calibration" in selected
    assert "tab:preview-calibration" in selected
    assert "tab:preview-efficiency" not in selected
    assert "tab:preview-error-analysis" not in selected
    assert "tab:paired-reversals" not in selected
    assert "tab:claim-evidence" not in selected


def test_many_dataset_primary_table_uses_compact_three_column_layout() -> None:
    rows = [
        {"dataset": dataset, "method": method, "value": str(value),
         "ci_low": "0.4", "ci_high": "0.7", "secondary_value": "0.8",
         "stress_value": "0.3", "calibration_value": "0.04"}
        for dataset in ("Cohort A", "Cohort B", "Cohort C")
        for method, value in (("Named method", 0.6), ("Named control", 0.5))
    ]
    table = _main_table(rows, "Response rate", {}, "maximize")
    assert table["MAIN_COLUMN_SPEC"] == "p{0.24\\textwidth} X c"
    assert "Complementary endpoints" not in table["MAIN_HEADER"]
    assert all(row.count(" & ") == 2 for row in table["MAIN_BODY"].splitlines())
    assert "\\textbf" in table["MAIN_BODY"]


@pytest.mark.parametrize('relation,topology', [('feedback', 'feedback'), ('logical', 'logical'),
                                             ('control', 'parallel'), ('temporal', 'temporal')])
def test_scientific_layout_depends_on_relations_not_domain_template(relation, topology):
    scene = {'schema': 1, 'objects': [
        {'id': f'object{i}', 'kind': 'operation', 'label': f'Named operation {i}',
         'source_path': 'experiments/EXPERIMENT_PLAN.md'} for i in range(10)
    ], 'relations': [{'from': 'object0', 'to': 'object1', 'kind': relation}]}
    assert validate_scientific_scene(scene) == []
    layout = plan_scientific_layout(scene)
    assert layout['topology'] == topology
    assert [len(panel) for panel in layout['panels']] == [8, 2]
    assert layout['split_required'] is True
    scene['relations'][0]['to'] = 'absent'
    assert 'absent endpoint' in ' '.join(validate_scientific_scene(scene))


def test_scientific_layout_splits_overloaded_branch_instead_of_shrinking() -> None:
    scene = {
        "schema": 1,
        "objects": [{
            "id": "shared_core", "kind": "operation", "label": "Shared core",
            "source_path": "experiments/METHOD_CONTRACT.json",
        }, *[{
            "id": f"branch_{index}", "kind": "operation",
            "label": f"Named branch {index}",
            "source_path": "experiments/METHOD_CONTRACT.json",
        } for index in range(5)]],
        "relations": [{
            "from": "shared_core", "to": f"branch_{index}", "kind": "data",
        } for index in range(5)],
    }

    layout = plan_scientific_layout(
        scene,
        complexity_budget={
            "maximum_primary_objects": 8,
            "maximum_primary_branches": 2,
            "maximum_visible_labels": 12,
        },
    )

    assert layout["split_required"] is True
    assert "primary_branch_budget" in layout["split_reasons"]
    assert [len(panel) for panel in layout["panels"]] == [3, 3, 2]
    assert all(
        contract["repeated_context_ids"] == ["shared_core"]
        for contract in layout["panel_contracts"]
    )
    assert layout["complexity"]["maximum_outgoing_branches"] == 5
    assert layout["minimum_font_pt"] >= 8
    assert layout["cross_panel_relations"] == []


def test_scientific_layout_uses_label_budget_and_moves_long_text_outward() -> None:
    scene = {
        "schema": 1,
        "objects": [{
            "id": f"step_{index}", "kind": "operation",
            "label": (
                "An intentionally verbose scientific operation requiring caption detail"
                if index == 0 else f"Operation {index}"
            ),
            "subitems": [
                {"id": f"step_{index}_a", "label": "Condition A"},
                {"id": f"step_{index}_b", "label": "Condition B"},
            ],
            "source_path": "experiments/METHOD_CONTRACT.json",
        } for index in range(4)],
        "relations": [{
            "from": f"step_{index}", "to": f"step_{index + 1}", "kind": "data",
        } for index in range(3)],
    }

    layout = plan_scientific_layout(
        scene,
        complexity_budget={
            "maximum_primary_objects": 8,
            "maximum_primary_branches": 2,
            "maximum_visible_labels": 6,
            "maximum_label_words": 6,
        },
    )

    assert layout["split_required"] is True
    assert [len(panel) for panel in layout["panels"]] == [2, 2]
    assert "visible_label_budget" in layout["split_reasons"]
    assert layout["label_rewrite_required"] == ["step_0"]
    assert layout["complexity_actions"] == {
        "split": True,
        "rewrite_labels": True,
        "move_secondary_detail_to_caption": True,
    }


def test_scientific_scene_rejects_unrelated_objects_and_scaffold_labels():
    scene = {'schema': 1, 'objects': [
        {'id': 'a', 'kind': 'input', 'label': 'Named scientific inputs',
         'source_path': 'experiments/EXPERIMENT_PLAN.md'},
        {'id': 'b', 'kind': 'output', 'label': 'Measured response',
         'source_path': 'experiments/EXPERIMENT_PLAN.md'},
    ], 'relations': []}
    issues = validate_scientific_scene(scene)
    assert any('placeholder' in issue for issue in issues)
    assert any('requires authored relations' in issue for issue in issues)


def test_semantic_table_compiler_groups_columns_and_splits_rows_without_shrinking():
    spec = ScientificTableSpec(
        question='Which control changes the scientific outcome?', caption='Named controls and outcomes.',
        label='tab:controls', columns=(TableColumn('name', 'Condition'),
            TableColumn('effect', 'Effect', 'number', 'Registered endpoint'),
            TableColumn('interval', '95% CI', 'interval', 'Registered endpoint')),
        independent_unit='Participant', uncertainty='95% participant-level confidence intervals',
        source_paths=('experiments/results/outcomes.csv',), max_rows_per_panel=16,
    )
    rows = [{'name': f'Named condition {i}', 'effect': '0.25', 'interval': '[0.10, 0.40]'}
            for i in range(17)]
    latex = compile_scientific_table(spec, rows)
    assert latex.count(r'\begin{table}') == 2
    assert r'\multicolumn{2}{c}{Registered endpoint}' in latex
    assert 'tab:controls-panel-2' in latex
    assert 'Participant' in latex
    assert r'\resizebox' not in latex
    assert 'scriptsize' not in latex
    assert all(str(i) in latex for i in range(17))


def test_math_scripts_do_not_hide_small_prose_in_pdf_font_gate():
    class Page:
        @staticmethod
        def get_text(_mode):
            return {'blocks': [{'lines': [{'spans': [
                {'text': 'x', 'font': 'CMMI10', 'size': 5},
                {'text': 'Method description', 'font': 'Arial', 'size': 9},
                {'text': '0.573', 'font': 'Arial', 'size': 6},
            ]}]}]}
    assert minimum_readable_font_pt(Page()) == 6


def test_named_math_subscript_is_not_small_prose() -> None:
    class Page:
        @staticmethod
        def get_text(_mode):
            return {'blocks': [{'lines': [{'spans': [
                {'text': 'L', 'font': 'CMSY10', 'size': 10.9, 'bbox': (10, 20, 17, 31), 'origin': (10, 29)},
                {'text': 'primary', 'font': 'LMRoman8-Regular', 'size': 7.97,
                 'bbox': (17, 25, 44, 33), 'origin': (17, 31)},
                {'text': 'Explanation', 'font': 'Arial', 'size': 9.0},
            ]}]}]}

    assert minimum_readable_font_pt(Page()) == 9.0


def test_small_roman_prose_still_fails_font_gate() -> None:
    class Page:
        @staticmethod
        def get_text(_mode):
            return {'blocks': [{'lines': [{'spans': [
                {'text': 'Small caption', 'font': 'LMRoman8-Regular', 'size': 7.0},
            ]}]}]}

    assert minimum_readable_font_pt(Page()) == 7.0


def test_pdf_overlap_checks_visible_lines_not_block_bounding_boxes() -> None:
    import fitz
    from server.services.pdf_review_inspection import _overlap_pairs

    paragraph = (fitz.Rect(72, 516, 125, 527), 'objective is', 0)
    equation = (fitz.Rect(240, 531, 325, 544), 'L = Lprimary', 1)
    assert _overlap_pairs([paragraph, equation]) == 0
    colliding = (fitz.Rect(90, 518, 140, 529), 'overlap', 2)
    assert _overlap_pairs([paragraph, colliding]) == 1


def test_final_pdf_gate_rejects_stale_source_or_pdf_reports(tmp_path):
    paper = tmp_path / 'paper'
    paper.mkdir()
    tex = paper / 'main.tex'
    tex.write_text(r'\documentclass{article}\begin{document}Named study.\end{document}', encoding='utf-8')
    pdf = paper / 'main.pdf'
    pdf.write_bytes(b'%PDF-fixture')
    class Compiler:
        @staticmethod
        def inspect_pdf_for_review(_pdf, preview_dir):
            return {'pages': [{'page': 1, 'visible_text_chars': 120,
                              'minimum_readable_font_pt': 9, 'possible_layout_findings': []}]}
    inspect_compiled_paper(Compiler(), tmp_path, pdf)
    assert validate_persisted_pdf_quality(tmp_path) == []
    pdf.write_bytes(b'%PDF-changed-fixture')
    assert 'PDF' in ' '.join(validate_persisted_pdf_quality(tmp_path))
    inspect_compiled_paper(Compiler(), tmp_path, pdf)
    tex.write_text(tex.read_text(encoding='utf-8') + '\nChanged source.', encoding='utf-8')
    assert 'sources' in ' '.join(validate_persisted_pdf_quality(tmp_path))
    assert pdf_layout_issues({})


def test_authoring_prompt_has_no_universal_layout_or_deterministic_edit_target():
    prompt = figure_authoring_prompt('project', 'Named direction', {'assets': [
        {'id': 'method_architecture', 'kind': 'figure', 'producer_kind': 'model'},
        {'id': 'deterministic_plot', 'kind': 'figure', 'producer_kind': 'deterministic'},
    ]}, 'Known sources')
    assert 'scientific_scene.objects' in prompt
    assert 'Reference papers establish visual quality, never a copied template' in prompt
    assert '1800' not in prompt
    assert 'deterministic_plot' not in prompt


def test_authoring_prompt_requires_regeneration_without_current_native_review(tmp_path):
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "FIGURE_MANIFEST.json").write_text(json.dumps({"figures": [{
        "id": "method_architecture", "metadata": {"visual_review_rounds": []},
    }]}), encoding="utf-8")
    prompt = figure_authoring_prompt(str(tmp_path), "Named direction", {"assets": [{
        "id": "method_architecture", "kind": "figure", "producer_kind": "model",
    }]}, "Known sources")

    assert 'MUST call generate_figure' in prompt
    assert '["method_architecture"]' in prompt
    assert "input for improvement, not completion" in prompt


def test_deterministic_plot_owner_obeys_new_placed_font_floor():
    source = _bar_script('data.csv', 'method', 'Named endpoint', 'plot', {
        'canvas': {'target_font_pt': 5, 'minimum_font_pt': 8,
                   'double_column_inches': 7.2, 'placed_width_inches': 6.5},
    })
    tree = ast.parse(source)
    settings = next(ast.literal_eval(node.args[0]) for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'update' and node.args
                    and isinstance(node.args[0], ast.Dict))
    for key in ('font.size', 'axes.labelsize', 'xtick.labelsize', 'ytick.labelsize'):
        assert settings[key] * 6.5 / 7.2 >= 8.0


def test_pdf_layout_findings_route_to_manifest_figure_owner(tmp_path):
    paper = tmp_path / 'paper'
    paper.mkdir()
    (paper / 'main.aux').write_text(r'\\newlabel{fig:main}{{1}{2}}', encoding='utf-8')
    figures = tmp_path / 'figures'
    figures.mkdir()
    (figures / 'FIGURE_MANIFEST.json').write_text(json.dumps({'figures': [{
        'id': 'main_comparison', 'label': 'fig:main', 'source_path': 'figures/main.svg',
    }]}), encoding='utf-8')
    findings = layout_repair_findings(tmp_path, ['page 2: possible overlapping text-block pair(s)'], '.merak/quality/paper-layout.json')
    assert findings[0]['owner_node'] == 'figure'
    assert findings[0]['asset_ids'] == ['main_comparison']
    assert findings[0]['target_files'] == ['figures/main.svg']


def test_scene_geometry_keeps_labels_at_print_floor_and_regions_disjoint():
    objects = [{'id': f'n{i}', 'kind': 'operation', 'label': 'A named scientific transformation'}
               for i in range(12)]
    relations = [{'from': f'n{i}', 'to': f'n{i+1}', 'kind': 'data'} for i in range(11)]
    geometry = solve_scientific_panel(objects, relations)
    assert geometry['width_pt'] == 468
    assert all(node['font_pt'] >= 8 for node in geometry['nodes'])
    for index, left in enumerate(geometry['nodes']):
        assert left['x'] + left['width'] <= geometry['width_pt']
        for right in geometry['nodes'][index+1:]:
            intersection_width = min(left['x']+left['width'], right['x']+right['width']) - max(left['x'], right['x'])
            intersection_height = min(left['y']+left['height'], right['y']+right['height']) - max(left['y'], right['y'])
            assert intersection_width <= 0 or intersection_height <= 0
