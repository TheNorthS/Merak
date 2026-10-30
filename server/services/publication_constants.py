"""Stable publication-style identifiers shared by classification services."""

NATURE_FIGURE_GUIDE_URL = (
    "https://research-figure-guide.nature.com/figures/"
    "preparing-figures-our-specifications/"
)
NATURE_PANEL_GUIDE_URL = (
    "https://research-figure-guide.nature.com/figures/"
    "building-and-exporting-figure-panels/"
)
FIELD_ADAPTIVE_VISUAL_GUIDE = "MERAK field-adaptive accessible vector contract"

IMPLEMENTATION_FAMILY_BY_RESEARCH_FAMILY: dict[str, str] = {
    "machine_learning": "machine_learning",
    "computer_systems": "computational_general",
    "computational_biology": "computational_general",
    "clinical_biomedical": "external_protocol",
    "experimental_natural_science": "computational_general",
    "social_behavioral": "external_protocol",
    "engineering_systems": "computational_general",
    "theoretical_formal": "formal_verification",
    "qualitative_humanities": "external_protocol",
    "generic_quantitative": "computational_general",
}
