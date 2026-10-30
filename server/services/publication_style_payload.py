"""Pure publication-style payload projection."""

from __future__ import annotations

from typing import Any


def ranked_matches(scores: dict[str, int]) -> list[dict[str, Any]]:
    return sorted(
        ({"id": key, "score": score} for key, score in scores.items() if score > 0),
        key=lambda item: (-item["score"], item["id"]),
    )


def style_payload(
    *,
    schema_version: int,
    family: str,
    family_spec: dict[str, Any],
    archetype: str,
    archetype_spec: dict[str, Any],
    venue_profile: dict[str, Any],
    implementation_family: str,
    family_matches: list[dict[str, Any]],
    archetype_matches: list[dict[str, Any]],
    family_overridden: bool,
    archetype_overridden: bool,
    evidence_contract: dict[str, Any],
    palette: dict[str, str],
    reference_guides: list[str],
) -> dict[str, Any]:
    nature_like = bool(venue_profile["nature_like"])
    fonts = ["STIX Two Text", "DejaVu Serif", "serif"] if family == "theoretical_formal" else ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"]
    return {
        "schema_version": schema_version,
        "family": family,
        "family_label": family_spec["label"],
        "study_archetype": archetype,
        "implementation_family": implementation_family,
        "classification": {
            "family_source": "user_override" if family_overridden else "inferred",
            "study_archetype_source": "user_override" if archetype_overridden else "inferred",
            "family_candidates": family_matches[:4],
            "study_archetype_candidates": archetype_matches[:4],
            "fallback_used": not family_matches and family == "generic_quantitative",
        },
        "target_venue": str(venue_profile["venue"]),
        "venue_profile": venue_profile,
        "visual_standard": "nature-accessible-vector-v1" if nature_like else "field-adaptive-accessible-vector-v2",
        "reference_guides": reference_guides,
        "reporting_standards": list(archetype_spec["reporting_standards"]),
        "required_evidence": list(archetype_spec["required_evidence"]),
        "domain_evidence_contract": evidence_contract,
        "section_emphasis": list(archetype_spec["section_emphasis"]),
        "canvas": {
            "single_column_mm": 89, "double_column_mm": 183,
            "single_column_inches": 3.50, "double_column_inches": 7.20,
            "target_font_pt": max(9.0, float(venue_profile["target_font_pt"])),
            'placed_width_inches': 6.5,
            "minimum_font_pt": 8.0,
            "maximum_font_pt": 10.0,
            "png_dpi": 450,
        },
        "fonts": fonts,
        "palette": dict(palette),
        "rules": [
            "Use axis lines and tick marks and label units when a quantity has units.",
            "Use a color-blind-safe palette plus marker or line-style redundancy.",
            "No background gridlines, drop shadows, decorative icons, or colored legend text.",
            "Prefer interval, dot, distribution, and direct-comparison plots over decorative bars.",
            "Export editable vector PDF and SVG plus a 450 dpi PNG preview.",
            "Keep panel labels alphabetical and preserve editable text and layers.",
            "Report sample size, uncertainty, and the data/provenance path for every estimate.",
        ],
        "figure_roles": list(family_spec["figure_roles"]),
        "table_roles": list(family_spec["table_roles"]),
        "reporting": dict(family_spec["reporting"]),
        "plot_types": list(dict.fromkeys([
            *family_spec["plot_types"], *archetype_spec["plot_types"],
        ])),
    }
