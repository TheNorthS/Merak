from __future__ import annotations

from pathlib import Path

from server.services.paper_profile import (
    EXEMPLAR_STATISTICS,
    FIGURE_ROLE_ALIASES,
    TABLE_ROLE_ALIASES,
    canonical_roles,
    paper_profile_service,
)


def test_empirical_profile_uses_real_main_body_exemplar_statistics() -> None:
    profile = paper_profile_service.build(
        target_venue="ICLR",
        evidence_mode="synthetic_preview",
        submission_eligible=False,
    )

    assert [item["main_text_words"] for item in EXEMPLAR_STATISTICS] == [
        4561,
        5170,
        5884,
    ]
    assert profile["main_text_words"] == [4500, 6500]
    assert profile["minimum_unique_citations"] == 30
    assert profile["figure_contract"]["minimum_distinct_graphics"] == 2
    assert profile["figure_contract"]["required_roles"] == ["method", "main_comparison"]
    assert profile["table_contract"]["minimum_tables"] == 1
    assert profile["table_contract"]["required_roles"] == ["main_results"]


def test_protocol_assets_cannot_impersonate_empirical_result_roles() -> None:
    figure_roles = canonical_roles(
        ["method", "evaluation_design", "internal_protocol"],
        FIGURE_ROLE_ALIASES,
    )
    table_roles = canonical_roles(
        ["study_design", "method_components"],
        TABLE_ROLE_ALIASES,
    )

    assert figure_roles == {"method", "evaluation_design"}
    assert table_roles == {"dataset_summary"}
    assert "main_comparison" not in figure_roles
    assert "main_results" not in table_roles
    assert "ablation" not in table_roles


def test_executed_and_synthetic_profiles_share_complete_submission_structure() -> None:
    preview = paper_profile_service.build(
        evidence_mode="synthetic_preview",
        submission_eligible=True,
    )
    executed = paper_profile_service.build(
        evidence_mode="executed",
        submission_eligible=True,
    )

    assert preview["figure_contract"] == executed["figure_contract"]
    assert preview["table_contract"] == executed["table_contract"]
    assert preview["publication_track"] == "simulation_draft"
    assert executed["publication_track"] == "empirical_submission"
    assert preview["evidence_policy"]["synthetic_preview_submission_eligible"] is False
    assert preview["submission_eligible"] is False


def test_domain_profiles_do_not_force_ml_ablation_and_compute_tables() -> None:
    clinical = paper_profile_service.build(
        evidence_mode="executed",
        submission_eligible=True,
        research_family="clinical_biomedical",
        study_archetype="diagnostic_prognostic",
    )
    theory = paper_profile_service.build(
        evidence_mode="executed",
        submission_eligible=True,
        research_family="theoretical_formal",
        study_archetype="formal_theory",
    )

    assert clinical["table_contract"]["required_roles"] == ["main_results"]
    assert "ablation" not in clinical["table_contract"]["required_roles"]
    assert theory["figure_contract"]["minimum_distinct_graphics"] == 2
    assert theory["table_contract"]["minimum_tables"] == 1
    assert theory["study_archetype"] == "formal_theory"
def test_planned_profile_exposes_final_bibliography_requirement_before_drafting(
    tmp_path: Path,
) -> None:
    requirement = paper_profile_service.bibliography_requirement(
        tmp_path,
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
            "target_venue": "ICLR",
            "research_family": "auto",
            "study_archetype": "auto",
        },
        direction="EEG foundation model robustness",
    )

    assert requirement == 30
