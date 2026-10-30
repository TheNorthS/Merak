"""Evidence-aware structural profiles for research manuscripts.

The profile describes scientific roles, not domain-specific filenames.  It is
derived from real peer manuscripts and gives drafting and acceptance the same
definition of a complete empirical paper.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from ..utils.atomic_write import atomic_write_json
from .simulation_policy import is_complete_evidence_mode


PROFILE_SCHEMA_VERSION = 3


EXEMPLAR_STATISTICS: tuple[dict[str, Any], ...] = (
    {
        "name": "LaBraM",
        "venue": "ICLR 2024",
        "arxiv_id": "2405.18765",
        "main_text_words": 4561,
        "main_text_figures": 5,
        "main_text_tables": 2,
        "unique_citations": 30,
    },
    {
        "name": "BIOT",
        "venue": "NeurIPS 2023",
        "arxiv_id": "2305.10351",
        "main_text_words": 5170,
        "main_text_figures": 4,
        "main_text_tables": 3,
        "unique_citations": 58,
    },
    {
        "name": "CBraMod",
        "venue": "ICLR 2025",
        "arxiv_id": "2412.07236",
        "main_text_words": 5884,
        "main_text_figures": 5,
        "main_text_tables": 4,
        "unique_citations": 56,
    },
)


FAMILY_MANUSCRIPT_CONTRACTS: dict[str, dict[str, Any]] = {
    "machine_learning": {
        "main_text_words": [4500, 7000], "citations": 30, "figures": 4, "tables": 4,
        "figure_roles": ["method", "evaluation_design", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "ablation",
                        "robustness_or_calibration"],
    },
    "computer_systems": {
        "main_text_words": [4500, 7500], "citations": 28, "figures": 4, "tables": 4,
        "figure_roles": ["method", "evaluation_design", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "ablation",
                        "robustness_or_calibration", "efficiency"],
    },
    "computational_biology": {
        "main_text_words": [4000, 7500], "citations": 35, "figures": 5, "tables": 3,
        "figure_roles": ["evaluation_design", "method", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "robustness_or_calibration"],
    },
    "clinical_biomedical": {
        "main_text_words": [3000, 6000], "citations": 25, "figures": 4, "tables": 3,
        "figure_roles": ["evaluation_design", "method", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "robustness_or_calibration"],
    },
    "experimental_natural_science": {
        "main_text_words": [3000, 6500], "citations": 30, "figures": 5, "tables": 2,
        "figure_roles": ["evaluation_design", "method", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results"],
    },
    "social_behavioral": {
        "main_text_words": [5000, 9000], "citations": 35, "figures": 3, "tables": 4,
        "figure_roles": ["evaluation_design", "main_comparison",
                         "robustness_or_error_analysis"],
        "table_roles": ["dataset_summary", "main_results", "ablation",
                        "robustness_or_calibration"],
    },
    "engineering_systems": {
        "main_text_words": [4500, 7500], "citations": 28, "figures": 4, "tables": 4,
        "figure_roles": ["method", "evaluation_design", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "ablation",
                        "robustness_or_calibration", "efficiency"],
    },
    "theoretical_formal": {
        "main_text_words": [3500, 8500], "citations": 20, "figures": 2, "tables": 2,
        "figure_roles": ["method", "main_comparison"],
        "table_roles": ["dataset_summary", "main_results"],
    },
    "qualitative_humanities": {
        "main_text_words": [4500, 9000], "citations": 30, "figures": 2, "tables": 3,
        "figure_roles": ["evaluation_design", "method", "main_comparison"],
        "table_roles": ["dataset_summary", "main_results", "robustness_or_calibration"],
    },
    "generic_quantitative": {
        "main_text_words": [4500, 6500], "citations": 30, "figures": 4, "tables": 4,
        "figure_roles": ["method", "evaluation_design", "main_comparison",
                         "robustness_or_error_analysis", "calibration_or_efficiency"],
        "table_roles": ["dataset_summary", "main_results", "ablation",
                        "robustness_or_calibration"],
    },
}


FIGURE_ROLE_ALIASES: dict[str, set[str]] = {
    "method": {"method", "architecture", "method_architecture"},
    "evaluation_design": {
        "evaluation_design", "data", "dataset", "study_overview",
        "evaluation", "cohort_flow",
    },
    "main_comparison": {"result", "main_result", "main_comparison"},
    "ablation": {"ablation", "component_analysis"},
    "robustness_or_error_analysis": {
        "robustness", "error_analysis", "sensitivity", "failure_analysis",
    },
    "calibration_or_efficiency": {
        "calibration", "risk_coverage", "efficiency", "scaling",
    },
}


TABLE_ROLE_ALIASES: dict[str, set[str]] = {
    "dataset_summary": {
        "dataset", "dataset_summary", "dataset_registry", "task_summary",
        "study_design",
    },
    "main_results": {"result", "main_result", "main_results"},
    "ablation": {"ablation", "component_ablation"},
    "robustness_or_calibration": {
        "robustness", "calibration", "robustness_calibration",
        "error_analysis",
    },
    "efficiency": {"efficiency", "compute", "parameter_efficiency"},
}


def _normalized_roles(values: Iterable[str]) -> set[str]:
    return {
        "_".join(str(value or "").strip().casefold().replace("-", " ").split())
        for value in values
        if str(value or "").strip()
    }


def canonical_roles(values: Iterable[str], aliases: dict[str, set[str]]) -> set[str]:
    normalized = _normalized_roles(values)
    return {
        role
        for role, candidates in aliases.items()
        if normalized & candidates
    }


def _planned_evidence(raw: dict[str, Any]) -> tuple[bool, str, bool]:
    run_experiment = raw.get("run_experiment") is True
    evidence_mode = (
        "executed"
        if run_experiment
        else str(
            raw.get("non_experiment_evidence_mode")
            or raw.get("evidence_mode")
            or "design_only"
        ).casefold()
    )
    return run_experiment, evidence_mode, bool(
        run_experiment or is_complete_evidence_mode(evidence_mode)
    )


def _required_roles(
    contract: dict[str, Any],
    empirical: bool,
) -> tuple[list[str], list[str]]:
    if empirical:
        return ['method', 'main_comparison'], ['main_results']
    return ['method'], []


class PaperProfileService:
    """Build and persist the manuscript profile selected for one project."""

    relative_path = Path("paper") / "PAPER_PROFILE.json"

    @staticmethod
    def publication_track(evidence_mode: str, submission_eligible: bool) -> str:
        mode = str(evidence_mode or "design_only").casefold()
        if mode == "synthetic_preview":
            return "simulation_draft"
        if is_complete_evidence_mode(mode):
            return "empirical_submission"
        return "protocol_draft"

    def build(
        self,
        *,
        target_venue: str = "",
        evidence_mode: str = "design_only",
        submission_eligible: bool = False,
        research_family: str = "generic_quantitative",
        study_archetype: str = "generic_empirical",
    ) -> dict[str, Any]:
        track = self.publication_track(evidence_mode, submission_eligible)
        empirical = track != "protocol_draft"
        family = (
            research_family
            if research_family in FAMILY_MANUSCRIPT_CONTRACTS
            else "generic_quantitative"
        )
        contract = FAMILY_MANUSCRIPT_CONTRACTS[family]
        required_figure_roles, required_table_roles = _required_roles(
            contract, empirical
        )
        profile = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "profile_id": (
                f"empirical-{family}-{study_archetype}-v3"
                if empirical else "scientific-protocol-v1"
            ),
            "research_family": family,
            "study_archetype": str(study_archetype or "generic_empirical"),
            "publication_track": track,
            "target_venue": str(target_venue or "unspecified"),
            "evidence_mode": str(evidence_mode or "design_only"),
            "submission_eligible": bool(submission_eligible and evidence_mode != "synthetic_preview"),
            "exemplar_basis": (
                list(EXEMPLAR_STATISTICS) if family == "machine_learning" else []
            ),
            "structural_basis": (
                "field-and-study-design publication contract; venue template remains authoritative"
            ),
            "main_text_words": list(contract["main_text_words"]) if empirical else [800, 5500],
            "abstract_words": [150, 250],
            "minimum_unique_bibliography_entries": int(contract["citations"]) if empirical else 5,
            "minimum_unique_citations": int(contract["citations"]) if empirical else 5,
            "target_unique_citations": (
                [int(contract["citations"]) + 5, int(contract["citations"]) + 25]
                if empirical else [15, 30]
            ),
            "figure_contract": {
                "minimum_distinct_graphics": 2 if empirical else 1,
                "target_distinct_graphics": (
                    [int(contract["figures"]), int(contract["figures"]) + 2]
                    if empirical else [2, 4]
                ),
                "required_roles": required_figure_roles,
            },
            "table_contract": {
                "minimum_tables": 1 if empirical else 0,
                "target_tables": (
                    [int(contract["tables"]), int(contract["tables"]) + 2]
                    if empirical else [2, 4]
                ),
                "required_roles": required_table_roles,
                "recommended_roles": (
                    ["efficiency"]
                    if empirical and "efficiency" not in required_table_roles else []
                ),
            },
            "evidence_policy": {
                "executed_result_roles_require_provenance": True,
                "synthetic_preview_may_satisfy_structure_only": False,
                "synthetic_preview_submission_eligible": False,
                "preview_values_must_be_explicitly_disclosed": True,
                "simulation_disclosure_location": "scientific_methods_and_end_disclosure",
                "simulation_warning_banners_allowed": False,
                "simulation_caption_caveats_allowed": True,
                "internal_evidence_mode_terms_allowed_in_rendered_text": False,
            },
        }
        return profile

    def planned(
        self,
        project_path: str | Path,
        *,
        options: dict[str, Any] | None = None,
        direction: str = "",
    ) -> dict[str, Any]:
        """Resolve the final manuscript contract before paper drafting starts.

        Literature retrieval runs well before ``PAPER_PROFILE.json`` is normally
        materialized. Returning the same profile here lets the literature gate
        enforce the bibliography needed by the eventual manuscript instead of a
        smaller, unrelated hard-coded threshold.
        """
        root = Path(project_path).expanduser().resolve()
        raw = dict(options or {})
        run_experiment, evidence_mode, submission_eligible = _planned_evidence(raw)
        target_venue = str(raw.get("target_venue") or "unspecified")
        configured_family = str(raw.get("research_family") or "")
        configured_archetype = str(raw.get("study_archetype") or "")

        stored = self.load(root)
        if stored:
            venue_matches = (
                not target_venue
                or target_venue == "unspecified"
                or str(stored.get("target_venue") or "") == target_venue
            )
            mode_matches = str(stored.get("evidence_mode") or "") == evidence_mode
            family_matches = (
                configured_family not in FAMILY_MANUSCRIPT_CONTRACTS
                or str(stored.get("research_family") or "") == configured_family
            )
            if venue_matches and mode_matches and family_matches:
                return stored

        context_parts = [
            str(direction or "").strip(),
            str(raw.get("research_direction") or "").strip(),
        ]
        for relative in (
            Path("literature") / "RESEARCH_BRIEF.md",
            Path("literature") / "survey.md",
        ):
            candidate = root / relative
            try:
                context_parts.append(
                    candidate.read_text(
                        encoding="utf-8-sig", errors="replace"
                    )[:6000]
                )
            except OSError:
                continue
        context = "\n".join(item for item in context_parts if item)

        # Local import avoids a module cycle: publication_style intentionally
        # has no dependency on the manuscript profile service.
        from .publication_style import publication_style_service

        publication_style = publication_style_service.build(
            context=context,
            target_venue=target_venue,
            research_family=configured_family,
            study_archetype=configured_archetype,
        )
        return self.build(
            target_venue=target_venue,
            evidence_mode=evidence_mode,
            submission_eligible=submission_eligible,
            research_family=str(
                publication_style.get("family") or "generic_quantitative"
            ),
            study_archetype=str(
                publication_style.get("study_archetype")
                or "generic_empirical"
            ),
        )

    def bibliography_requirement(
        self,
        project_path: str | Path,
        *,
        options: dict[str, Any] | None = None,
        direction: str = "",
    ) -> int:
        profile = self.planned(
            project_path,
            options=options,
            direction=direction,
        )
        return max(
            1,
            int(profile.get("minimum_unique_bibliography_entries") or 1),
        )
    def prepare(
        self,
        project_path: str | Path,
        *,
        target_venue: str = "",
        evidence_mode: str = "design_only",
        submission_eligible: bool = False,
        research_family: str = "generic_quantitative",
        study_archetype: str = "generic_empirical",
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        target = root / self.relative_path
        scientific_payload = self.build(
            target_venue=target_venue,
            evidence_mode=evidence_mode,
            submission_eligible=submission_eligible,
            research_family=research_family,
            study_archetype=study_archetype,
        )
        existing = self.load(root)
        existing_scientific = {
            key: value
            for key, value in existing.items()
            if key != "generated_at"
        }
        # PAPER_PROFILE is an acceptance input for literature sizing.  A
        # timestamp-only rewrite during paper drafting used to invalidate the
        # accepted literature node and cascade through the entire workflow on
        # every resume.  Preserve the file byte-for-byte when its scientific
        # contract has not changed.
        if existing and existing_scientific == scientific_payload:
            return existing
        payload = {**scientific_payload, "generated_at": time.time()}
        atomic_write_json(target, payload)
        return payload

    def load(self, project_path: str | Path) -> dict[str, Any]:
        target = Path(project_path).expanduser().resolve() / self.relative_path
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


paper_profile_service = PaperProfileService()
