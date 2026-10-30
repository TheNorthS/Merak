"""Declarative LaTeX venue and custom-template configuration."""

from __future__ import annotations

from typing import Any

VENUE_TEMPLATE_BUNDLES: dict[str, dict[str, Any]] = {
    "iclr": {
        "label": "ICLR 2026 anonymous submission",
        "assets": ("iclr2026_conference.sty", "iclr2026_conference.bst"),
        "documentclass": r"\documentclass{article}",
        "venue_preamble": r"\usepackage{iclr2026_conference,times}",
        "bibliography_style": "iclr2026_conference", "title_mode": "standard",
        "hyperref": True,
    },
    "neurips": {
        "label": "NeurIPS 2026 anonymous main-track submission",
        "assets": ("neurips_2026.sty",), "documentclass": r"\documentclass{article}",
        "venue_preamble": r"\usepackage{neurips_2026}",
        "bibliography_style": "plainnat", "title_mode": "standard", "hyperref": True,
    },
    "icml": {
        "label": "ICML 2026 anonymous submission", "assets": ("icml2026.sty",),
        "documentclass": r"\documentclass{article}",
        "venue_preamble": r"\usepackage{icml2026}",
        "bibliography_style": "plainnat", "title_mode": "icml", "hyperref": True,
    },
    "cvpr": {
        "label": "CVPR 2026 anonymous review submission",
        "assets": ("cvpr.sty", "cvpr.bst"),
        "documentclass": r"\documentclass[10pt,twocolumn,letterpaper]{article}",
        "venue_preamble": (
            r"\usepackage[review]{cvpr}" "\n" r"\def\paperID{*****}" "\n"
            r"\def\confName{CVPR}" "\n" r"\def\confYear{2026}"
        ),
        "bibliography_style": "cvpr", "title_mode": "standard", "hyperref": True,
    },
    "acl": {
        "label": "ACL 2026 anonymous review submission",
        "assets": ("acl.sty", "acl_natbib.bst"),
        "documentclass": r"\documentclass[11pt]{article}",
        "venue_preamble": (
            r"\usepackage[review]{acl}" "\n" r"\usepackage{times}" "\n"
            r"\usepackage{latexsym}"
        ),
        "bibliography_style": "", "title_mode": "standard", "hyperref": False,
    },
    "aaai": {
        "label": "AAAI 2026 anonymous submission",
        "assets": ("aaai2026.sty", "aaai2026.bst"),
        "documentclass": "\\def\\aaaianonymous{true}\n\\documentclass[letterpaper]{article}",
        "venue_preamble": (
            r"\usepackage[submission]{aaai2026}" "\n" r"\usepackage{times}" "\n"
            r"\usepackage{helvet}" "\n" r"\usepackage{courier}" "\n"
            r"\usepackage[hyphens]{url}" "\n" r"\usepackage{natbib}"
        ),
        "bibliography_style": "", "title_mode": "standard", "hyperref": False,
    },
}

VENUE_FAMILY_BUNDLES: dict[str, dict[str, Any]] = {
    "nature_science": {
        "label": "Nature/Science-family editorial manuscript",
        "documentclass": r"\documentclass[11pt]{article}",
        "venue_preamble": r"\usepackage[numbers,sort&compress]{natbib}",
        "bibliography_style": "unsrtnat", "title_mode": "standard",
        "hyperref": True, "geometry": r"\usepackage[margin=1in]{geometry}" + "\n",
    },
    "biomedical_journal": {
        "label": "Biomedical journal manuscript",
        "documentclass": r"\documentclass[11pt]{article}",
        "venue_preamble": r"\usepackage[numbers,sort&compress]{natbib}",
        "bibliography_style": "unsrtnat", "title_mode": "standard",
        "hyperref": True, "geometry": r"\usepackage[margin=1in]{geometry}" + "\n",
    },
    "ieee_acm_journal": {
        "label": "IEEE/ACM-style two-column review manuscript",
        "documentclass": r"\documentclass[10pt,twocolumn]{article}",
        "venue_preamble": r"\usepackage[numbers,sort&compress]{natbib}",
        "bibliography_style": "unsrtnat", "title_mode": "standard",
        "hyperref": True, "geometry": r"\usepackage[margin=0.75in]{geometry}" + "\n",
    },
    "mathematics_theory": {
        "label": "Mathematics and formal-theory manuscript",
        "documentclass": r"\documentclass[11pt]{amsart}",
        "venue_preamble": r"\usepackage{natbib}", "bibliography_style": "plainnat",
        "title_mode": "standard", "hyperref": True, "geometry": "",
        "abstract_before_title": True,
    },
    "social_qualitative": {
        "label": "Social-science and qualitative journal manuscript",
        "documentclass": r"\documentclass[11pt]{article}",
        "venue_preamble": r"\usepackage[authoryear,round]{natbib}",
        "bibliography_style": "plainnat", "title_mode": "standard",
        "hyperref": True, "geometry": r"\usepackage[margin=1in]{geometry}" + "\n",
    },
    "generic_journal": {
        "label": "Generic peer-review manuscript",
        "documentclass": r"\documentclass[11pt]{article}",
        "venue_preamble": r"\usepackage{natbib}", "bibliography_style": "plainnat",
        "title_mode": "standard", "hyperref": True,
        "geometry": r"\usepackage[margin=1in]{geometry}" + "\n",
    },
}

CUSTOM_TEMPLATE_EXTENSIONS = frozenset({
    ".tex", ".cls", ".sty", ".bst", ".bbx", ".cbx", ".def", ".cfg",
    ".clo", ".fd", ".lbx", ".ldf", ".ins", ".dtx", ".pdf", ".png",
    ".jpg", ".jpeg", ".eps", ".svg",
})
CUSTOM_TEMPLATE_DEPENDENCY_EXTENSIONS = CUSTOM_TEMPLATE_EXTENSIONS - {".zip"}
CUSTOM_TEMPLATE_RESERVED_TARGETS = frozenset({
    "main.tex", "references.bib", "title.txt", "draft_state.json",
    "paper_style_profile.json", "paper_profile.json", "section_contracts.json",
    "section_reviews.json", "contribution_blueprint.md", "cross_section_review.md",
    "sections", "tables", "revisions", "venue_template",
})
CUSTOM_TEMPLATE_CONTENT_MARKERS = (
    "{{MERAK_CONTENT}}", "% MERAK:CONTENT", "%% MERAK_CONTENT",
)
