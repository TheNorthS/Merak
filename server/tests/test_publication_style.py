from __future__ import annotations

import json

import pytest

from server.services.publication_style import publication_style_service
from server.services.scientific_assets import scientific_asset_service


@pytest.mark.parametrize(
    ("direction", "venue", "family"),
    [
        ("Foundation model for robust representation learning", "ICLR", "machine_learning"),
        ("Database query optimization under tail latency", "SIGMOD", "computer_systems"),
        ("Single-cell transcriptomics and pathway prediction", "Nature Methods", "computational_biology"),
        ("External validation of a clinical prognosis model", "JAMA", "clinical_biomedical"),
        ("Catalyst dose-response under spectroscopy", "Nature Chemistry", "experimental_natural_science"),
        ("Causal policy effects in a household survey", "AER", "social_behavioral"),
        ("Robotics control under latency and hardware faults", "T-RO", "engineering_systems"),
        ("A theorem with a lower bound and constructive proof", "STOC", "theoretical_formal"),
        ("Interview-based thematic analysis with negative cases", "", "qualitative_humanities"),
        ("A quantitative comparison of alternative estimates", "", "generic_quantitative"),
    ],
)
def test_publication_style_selects_domain_reporting_contract(
    direction: str,
    venue: str,
    family: str,
) -> None:
    profile = publication_style_service.build(
        context=direction,
        target_venue=venue,
    )

    assert profile["family"] == family
    assert len(profile["figure_roles"]) >= 5
    assert len(profile["table_roles"]) >= 5
    assert profile["reporting"]["secondary_label"]
    assert profile["canvas"]["single_column_mm"] == 89
    assert profile["canvas"]["double_column_mm"] == 183
    assert profile["canvas"]["png_dpi"] == 450
    assert profile["reference_guides"]
    assert profile["study_archetype"]
    assert profile["required_evidence"]


@pytest.mark.parametrize(
    ("direction", "archetype"),
    [
        ("Randomized placebo-controlled intervention trial", "intervention_trial"),
        ("External validation of a diagnostic prognosis model", "diagnostic_prognostic"),
        ("Single-cell transcriptomics with batch correction", "omics_discovery"),
        ("Finite-element simulation with convergence verification", "simulation_modeling"),
        ("Formal theorem, lemma, proof, and counterexample", "formal_theory"),
        ("Ethnographic interviews with thematic coding", "qualitative_mixed"),
        ("Distributed testbed with throughput and tail latency", "systems_testbed"),
    ],
)
def test_publication_style_selects_study_design_contract(
    direction: str,
    archetype: str,
) -> None:
    profile = publication_style_service.build(context=direction)

    assert profile["study_archetype"] == archetype
    assert profile["reporting_standards"]
    assert len(profile["plot_types"]) >= 3


def test_generic_project_scaffold_words_do_not_force_social_or_lab_classification() -> None:
    profile = publication_style_service.build(
        context=(
            "# Survey\nEvidence-grounded review\n"
            "experiment:\n  primary_metric: score\n"
            "baseline: matched workflow"
        )
    )

    assert profile["family"] == "generic_quantitative"
    assert profile["study_archetype"] == "algorithm_benchmark"


def test_publication_style_is_persisted_for_downstream_renderers(tmp_path) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({"title": "Multi-omics biomarker discovery"}),
        encoding="utf-8",
    )

    profile = publication_style_service.prepare(
        tmp_path,
        target_venue="Nature Biotechnology",
    )
    saved = json.loads(
        (tmp_path / "paper" / "PUBLICATION_STYLE.json").read_text(
            encoding="utf-8"
        )
    )

    assert profile["family"] == "computational_biology"
    assert saved["visual_standard"] == "nature-accessible-vector-v1"
    assert saved["canvas"]["target_font_pt"] == 9.0
    assert saved["canvas"]["minimum_font_pt"] >= 8.0


def test_nature_figure_guidance_is_not_forced_on_other_venues() -> None:
    profile = publication_style_service.build(
        context="Distributed systems testbed with tail latency",
        target_venue="USENIX ATC",
    )

    assert profile["visual_standard"] == "field-adaptive-accessible-vector-v2"
    assert not any(
        "research-figure-guide.nature.com" in guide
        for guide in profile["reference_guides"]
    )


@pytest.mark.parametrize(
    ("direction", "implementation_family"),
    [
        ("Transformer benchmark with accuracy and ablation", "machine_learning"),
        ("Randomized clinical intervention trial", "external_protocol"),
        ("Finite-element numerical simulation with convergence", "computational_general"),
        ("Theorem and machine-checked proof with counterexample", "formal_verification"),
        ("Ethnographic interview thematic analysis", "external_protocol"),
    ],
)
def test_publication_style_exposes_implementation_and_domain_contract(
    direction: str,
    implementation_family: str,
) -> None:
    profile = publication_style_service.build(context=direction)

    assert profile["implementation_family"] == implementation_family
    contract = profile["domain_evidence_contract"]
    assert contract["analysis_unit"]
    assert contract["provenance"]
    assert contract["visual_priorities"]


def test_scientific_asset_plan_embeds_style_without_creating_paper_directory(
    tmp_path,
) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "experiments").mkdir()
    (tmp_path / "ideas/SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "status": "accepted", "title": "Constructive bounded theorem",
        "hypothesis": "A stated bounded assumption supports the constructive conclusion.",
        "claims": [{"id": "C1", "statement": "The constructive result follows under the declared assumption.",
                    "publication_statement": "The constructive result follows under the declared assumption."}],
        "mechanisms": [{"id": "M1", "name": "Constructive implication", "publication_name": "Constructive implication",
                        "publication_description": "Derives the stated conclusion from the bounded assumption.",
                        "publication_evaluation": "Check the declared proof obligation."}],
        "publication": {"language": "en", "title": "Constructive Bounded Theorem", "method_name": "Constructive implication",
                        "contribution_type": "theory_proof", "comparator_names": ["Classical construction"]},
    }), encoding="utf-8")
    (tmp_path / "experiments/METHOD_CONTRACT.json").write_text(json.dumps({
        "schema": 2, "scientific_scene": {"schema": 1, "objects": [
            {"id": "bounded_assumption", "kind": "assumption", "label": "Bounded assumption", "source_path": "experiments/METHOD_CONTRACT.json"},
            {"id": "constructive_conclusion", "kind": "theorem", "label": "Constructive conclusion", "source_path": "experiments/METHOD_CONTRACT.json"},
        ], "relations": [{"from": "bounded_assumption", "to": "constructive_conclusion", "kind": "logical"}]},
    }), encoding="utf-8")
    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        direction="Formal theorem with a constructive proof",
        target_venue="STOC",
    )

    assert plan["publication_style"]["family"] == "theoretical_formal"
    assert plan["publication_style_contract"]["study_archetype"] == "formal_theory"
    assert not (tmp_path / "paper").exists()
