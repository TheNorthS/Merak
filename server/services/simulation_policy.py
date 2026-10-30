"""Shared manuscript policy for deterministic simulation studies."""

from __future__ import annotations

import re
from typing import Any

from .simulation_manifest_validation import (
    claim_contract_issues,
    claim_issues,
    core_issues,
    evidence_package_issues,
    figure_issues,
    ranking_issues,
    version,
)


SIMULATION_MANIFEST_SCHEMA = 11
# Version the renderer independently from the scientific evidence schema.
# Raising this value refreshes current-schema figures/tables exactly once
# without pretending that the benchmark data contract itself has changed.
SIMULATION_RENDERER_VERSION = 18
SIMULATION_STABLE_ROLES = (
    "main_comparison",
    "component_ablation",
    "training_dynamics",
    "robustness_sensitivity",
    "error_analysis",
    "calibration_risk_coverage",
    "efficiency_tradeoff",
)
SIMULATION_STABLE_IDS = {
    "main_comparison": "synthetic_preview_main_comparison",
    "component_ablation": "synthetic_preview_ablation",
    "training_dynamics": "synthetic_preview_training_dynamics",
    "robustness_sensitivity": "synthetic_preview_robustness",
    "error_analysis": "synthetic_preview_error_analysis",
    "calibration_risk_coverage": "synthetic_preview_calibration",
    "efficiency_tradeoff": "synthetic_preview_efficiency",
}
SIMULATION_PLOT_FAMILIES = {
    "main_comparison": "ranked_interval_forest",
    "component_ablation": "ablation_delta_waterfall",
    "training_dynamics": "learning_progression_curve",
    "robustness_sensitivity": "stress_response_curve",
    "error_analysis": "slice_risk_bar",
    "calibration_risk_coverage": "risk_coverage_frontier",
    "efficiency_tradeoff": "resource_pareto_frontier",
}

# Evidence tracks that are allowed to produce a complete manuscript. The
# synthetic track is deliberately included here: its generator/provenance
# details remain machine-side metadata, while the rendered artifact follows
# the same scientific-asset contract as an executed study.
COMPLETE_EVIDENCE_MODES = frozenset({
    "executed",
    "existing_results",
    "secondary_analysis",
    "synthetic_preview",
})


def is_complete_evidence_mode(value: Any) -> bool:
    """Return whether an evidence mode can drive a complete manuscript.

    ``synthetic_preview`` is an internal routing name only. Callers should
    never copy it into rendered prose; use this helper for eligibility logic.
    """
    return str(value or "").strip().casefold() in COMPLETE_EVIDENCE_MODES


def simulation_manifest_contract_issues(payload: Any) -> list[str]:
    """Validate the versioned semantic contract, excluding filesystem hashes."""

    if not isinstance(payload, dict):
        return ["manifest is not a JSON object"]
    issues, _core = core_issues(
        payload,
        schema=SIMULATION_MANIFEST_SCHEMA,
        renderer=SIMULATION_RENDERER_VERSION,
        roles=SIMULATION_STABLE_ROLES,
        ids=SIMULATION_STABLE_IDS,
        plot_families=SIMULATION_PLOT_FAMILIES,
    )
    figure_findings, figure_context = figure_issues(
        payload,
        ids=SIMULATION_STABLE_IDS,
        plot_families=SIMULATION_PLOT_FAMILIES,
    )
    issues.extend(figure_findings)
    claim_findings, claim_context = claim_issues(
        payload, figure_context["figures"]
    )
    issues.extend(claim_findings)
    issues.extend(claim_contract_issues(
        payload,
        claim_context["claim_ids"],
        claim_context["claim_map"],
        claim_context["declared_data"],
    ))
    extended = version(payload, "renderer_version") >= 11
    issues.extend(evidence_package_issues(
        payload, claim_context["declared_data"], extended=extended
    ))
    if extended:
        issues.extend(ranking_issues(payload))
    return issues



SIMULATION_END_DISCLOSURE_TITLE = "Simulation Study Disclosure"
SIMULATION_END_DISCLOSURE = (
    "The generated numerical results and their corresponding quantitative tables "
    "and plots come from the deterministic scenario construction recorded in the "
    "accompanying configuration, source code, and provenance artifacts. They are "
    "not measurements from physical, clinical, field, or production experiments. "
    "Conceptual diagrams and prospective design tables describe the proposed "
    "method or study protocol; they are not simulated observations or evidence "
    "that those procedures were executed."
)
# UI-like warnings and repeated evidence-mode labels are excluded from
# rendered manuscripts. One canonical end disclosure is permitted; detailed
# generator provenance remains in machine-readable sidecars.
FORBIDDEN_RENDERED_SIMULATION_LABELS = (
    "SYNTHETIC PREVIEW -- NOT FOR SUBMISSION",
    "NOT EXPERIMENTAL EVIDENCE",
    "NOT EXPERIMENTAL RESULTS",
    "synthetic preview",
    "simulation preview",
    "illustrative values",
    "results preview and replacement plan",
    "findings preview and replacement plan",
)


_VISIBLE_WATERMARK_RE = re.compile(
    r"\\documentclass\s*\[(?=[^\]]*\b(?:authordraft|draft)\b)[^\]]*\]"
    r"\s*\{\s*acmart\s*\}"
    r"|\\PassOptionsToClass\s*\{(?=[^}]*\b(?:authordraft|draft)\b)[^}]*\}"
    r"\s*\{\s*acmart\s*\}"
    r"|\\usepackage(?:\s*\[[^\]]*\])?\s*\{[^}]*\b"
    r"(?:draftwatermark|xwatermark|draftcopy|prelim2e)\b[^}]*\}"
    r"|\\(?:SetWatermark[A-Za-z@]*|Draftwatermark|"
    r"watermarksetup|draftcopy(?:Name|SetGrey|LastPage)?)\b"
    r"|\\newwatermark\b\*?",
    flags=re.IGNORECASE,
)
_SECTION_RE = re.compile(
    r"\\(section|subsection|subsubsection)\*?\s*\{([^{}]*)\}",
    flags=re.IGNORECASE | re.DOTALL,
)
_DISCLOSURE_RE = re.compile(
    r"\s+".join(
        re.escape(token) for token in SIMULATION_END_DISCLOSURE.split()
    ),
    flags=re.IGNORECASE,
)
_DISCLOSURE_TITLE_RE = re.compile(
    r"\s+".join(
        re.escape(token) for token in SIMULATION_END_DISCLOSURE_TITLE.split()
    ),
    flags=re.IGNORECASE,
)
_CONCLUSION_MARKER_RE = re.compile(
    r"\\input\s*\{\s*sections/08_conclusion(?:\.tex)?\s*\}"
    r"|\\section\*?\s*\{\s*Conclusion\s*\}",
    flags=re.IGNORECASE,
)
_END_MATTER_BOUNDARY_RE = re.compile(
    r"\\bibliography\s*\{|\\printbibliography\b|"
    r"\\begin\s*\{\s*thebibliography\s*\}|\\end\s*\{\s*document\s*\}",
    flags=re.IGNORECASE,
)

# Runtime labels are not scientific prose. Simulation and synthetic data are
# legitimate methodological descriptions and must not be suppressed.
_RENDERED_MODE_FRAMING_RE = re.compile(
    r"\bpreview\b|"
    r"\bevidence[- ]mode\b|\bsubmission[- ]eligib(?:le|ility)\b|"
    r"\bnot\s+for\s+submission\b|\bnot\s+experimental\s+evidence\b|"
    r"\b(?:manuscript|paper|results?|figures?|tables?)\s+draft\b|"
    r"\bdraft\s+(?:manuscript|paper|results?|figures?|tables?|status)\b",
    flags=re.IGNORECASE,
)

_NON_RENDERED_COMMAND_RE = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage|input|include|bibliography|"
    r"bibliographystyle|label|ref|pageref|url|"
    r"eqref|autoref|cref|Cref|cite[a-zA-Z]*|parencite|textcite|autocite|"
    r"footcite|includegraphics)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{[^{}]*\}",
    flags=re.IGNORECASE,
)
_HREF_PREFIX_RE = re.compile(
    r"\\href(?:\s*\[[^\]]*\])?\s*\{[^{}]*\}\s*",
    flags=re.IGNORECASE,
)
_GRAPHICSPATH_RE = re.compile(
    r"\\graphicspath\s*\{(?:\s*\{[^{}]*\}\s*)+\}",
    flags=re.IGNORECASE,
)
_LATEX_COMMAND_RE = re.compile(
    r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?",
)


def _mask_latex_comments(text: str) -> str:
    """Mask comments without changing offsets used for section attribution."""
    masked: list[str] = []
    for line in str(text or "").splitlines(keepends=True):
        cut = len(line)
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
        if cut == len(line):
            masked.append(line)
            continue
        suffix = line[cut:]
        masked.append(line[:cut] + "".join(
            character if character in "\r\n" else " "
            for character in suffix
        ))
    return "".join(masked)


def _latex_visible_search_text(text: str) -> str:
    """Return rendered-prose-like text while preserving source offsets.

    Formatting commands such as ``\\emph{...}`` retain their visible argument;
    non-rendered plumbing such as ``\\input{synthetic_preview_figures}`` is
    masked completely. Keeping string length stable lets disclosure matches be
    attributed to the correct LaTeX section hierarchy.
    """
    visible = _mask_latex_comments(text)
    for non_rendered in (_GRAPHICSPATH_RE, _HREF_PREFIX_RE):
        visible = non_rendered.sub(
            lambda match: " " * len(match.group(0)),
            visible,
        )
    visible = _NON_RENDERED_COMMAND_RE.sub(
        lambda match: " " * len(match.group(0)),
        visible,
    )
    visible = _LATEX_COMMAND_RE.sub(
        lambda match: " " * len(match.group(0)),
        visible,
    )
    return "".join(
        " " if character in "{}[]~" else character
        for character in visible
    )


def visible_latex_prose(text: str) -> str:
    """Extract normalized rendered prose, excluding paths, labels and comments."""
    return " ".join(_latex_visible_search_text(text).split())


def rendered_mode_framing_hits(text: str) -> tuple[str, ...]:
    """Return visible simulation/preview/draft framing tokens."""
    prose = visible_latex_prose(text)
    return tuple(dict.fromkeys(
        " ".join(match.group(0).split())
        for match in _RENDERED_MODE_FRAMING_RE.finditer(prose)
    ))


def rendered_mode_framing_hits_outside_end_disclosure(
    text: str,
) -> tuple[str, ...]:
    """Return internal-mode framing outside the one permitted end disclosure."""
    visible = _latex_visible_search_text(text)
    for pattern in (_DISCLOSURE_RE, _DISCLOSURE_TITLE_RE):
        visible = pattern.sub(
            lambda match: " " * len(match.group(0)),
            visible,
        )
    prose = " ".join(visible.split())
    return tuple(dict.fromkeys(
        " ".join(match.group(0).split())
        for match in _RENDERED_MODE_FRAMING_RE.finditer(prose)
    ))


def strip_latex_comments(text: str) -> str:
    """Remove unescaped LaTeX comments while preserving source line structure."""
    cleaned: list[str] = []
    for line in str(text or "").splitlines(keepends=True):
        cut = len(line)
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
        suffix = "\n" if line.endswith(("\n", "\r")) else ""
        cleaned.append(line[:cut].rstrip("\r\n") + suffix)
    return "".join(cleaned)


def visible_watermark_commands(text: str) -> tuple[str, ...]:
    """Return visible watermark/draft-stamp commands outside LaTeX comments."""
    uncommented = strip_latex_comments(text)
    return tuple(dict.fromkeys(
        " ".join(match.group(0).split())
        for match in _VISIBLE_WATERMARK_RE.finditer(uncommented)
    ))


def simulation_disclosure_report(text: str) -> dict[str, Any]:
    """Count the disclosure and verify that it is final end matter."""
    uncommented = _mask_latex_comments(text)
    searchable = _latex_visible_search_text(text)
    headings = list(_SECTION_RE.finditer(uncommented))
    matches = list(_DISCLOSURE_RE.finditer(searchable))
    conclusion_markers = list(_CONCLUSION_MARKER_RE.finditer(uncommented))
    conclusion_end = conclusion_markers[-1].end() if conclusion_markers else -1
    end_boundary_match = _END_MATTER_BOUNDARY_RE.search(
        uncommented,
        conclusion_end if conclusion_end >= 0 else 0,
    )
    end_boundary = (
        end_boundary_match.start()
        if end_boundary_match is not None
        else len(uncommented)
    )
    end_matter_count = 0
    section_titles: list[list[str]] = []
    levels = {"section": 1, "subsection": 2, "subsubsection": 3}

    for disclosure in matches:
        hierarchy: dict[int, str] = {}
        for heading in headings:
            if heading.end() > disclosure.start():
                break
            level = levels[heading.group(1).casefold()]
            hierarchy[level] = " ".join(heading.group(2).split())
            for deeper in tuple(key for key in hierarchy if key > level):
                hierarchy.pop(deeper, None)
        titles = [hierarchy[key] for key in sorted(hierarchy)]
        section_titles.append(titles)
        disclosure_heading = (
            titles[-1].strip().casefold()
            if titles
            else ""
        )
        if (
            conclusion_end >= 0
            and conclusion_end < disclosure.start() < end_boundary
            and disclosure_heading
            == SIMULATION_END_DISCLOSURE_TITLE.casefold()
        ):
            end_matter_count += 1

    return {
        "count": len(matches),
        "end_matter_count": end_matter_count,
        "outside_end_matter_count": len(matches) - end_matter_count,
        "section_titles": section_titles,
    }
