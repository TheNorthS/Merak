from __future__ import annotations

import pytest

from server.services.simulation_policy import (
    SIMULATION_END_DISCLOSURE,
    SIMULATION_END_DISCLOSURE_TITLE,
    rendered_mode_framing_hits,
    rendered_mode_framing_hits_outside_end_disclosure,
    simulation_disclosure_report,
    strip_latex_comments,
    visible_latex_prose,
    visible_watermark_commands,
)


@pytest.mark.parametrize(
    "source",
    [
        r"\usepackage{draftwatermark}",
        r"\usepackage[printwatermark]{xwatermark}",
        r"\usepackage{xcolor,draftcopy}",
        r"\usepackage{prelim2e}",
        r"\SetWatermarkText{DRAFT}",
        r"\SetWatermarkScale{2}",
        r"\newwatermark*[allpages]{DRAFT}",
        r"\draftcopyName{DRAFT}{100}",
        r"\documentclass[authordraft]{acmart}",
        r"\documentclass[sigconf,draft,anonymous]{acmart}",
        r"\PassOptionsToClass{authordraft}{acmart}",
        r"\PassOptionsToClass{anonymous,draft}{acmart}",
    ],
)
def test_visible_watermark_commands_cover_common_latex_mechanisms(
    source: str,
) -> None:
    assert visible_watermark_commands(source)


def test_visible_watermark_commands_ignore_comments_and_plain_prose() -> None:
    source = (
        "% \\usepackage{draftwatermark}\n"
        "% \\documentclass[authordraft]{acmart}\n"
        "% \\PassOptionsToClass{draft}{acmart}\n"
        "\\documentclass[sigconf,anonymous]{acmart}\n"
        "\\PassOptionsToClass{review}{acmart}\n"
        "The validator prevents a watermark from being added.\n"
        "Accuracy improved by 5\\% on the registered split.\n"
    )
    assert visible_watermark_commands(source) == ()
    assert "5\\%" in strip_latex_comments(source)


def test_simulation_disclosure_report_requires_final_end_matter() -> None:
    valid = (
        "\\section{Conclusion}\nThe registered findings are bounded.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        "\\bibliography{references}\n"
    )
    misplaced = (
        "\\section{Introduction}\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        "\\section{Conclusion}\nFinal finding.\n"
    )
    after_bibliography = (
        "\\section{Conclusion}\nFinal finding.\n"
        "\\bibliography{references}\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
    )

    assert simulation_disclosure_report(valid) == {
        "count": 1,
        "end_matter_count": 1,
        "outside_end_matter_count": 0,
        "section_titles": [[SIMULATION_END_DISCLOSURE_TITLE]],
    }
    assert simulation_disclosure_report(misplaced)["end_matter_count"] == 0
    assert simulation_disclosure_report(after_bibliography)["end_matter_count"] == 0


def test_simulation_disclosure_report_ignores_comments_and_counts_repeats() -> None:
    commented = (
        "\\section{Conclusion}\n"
        f"% {SIMULATION_END_DISCLOSURE}\n"
    )
    repeated = (
        "\\section{Conclusion}\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
    )

    assert simulation_disclosure_report(commented)["count"] == 0
    assert simulation_disclosure_report(repeated)["count"] == 2


def test_simulation_disclosure_report_uses_rendered_prose_not_tex_bytes() -> None:
    formatted = (
        "\\section{Conclusion}\nFinal finding.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        + SIMULATION_END_DISCLOSURE.replace('deterministic scenario construction',
            r'\emph{deterministic scenario construction}') + '\n'
        + "\\end{document}\n"
    )

    report = simulation_disclosure_report(formatted)

    assert report["count"] == 1
    assert report["end_matter_count"] == 1


def test_disclosure_distinguishes_generated_quantities_from_prospective_design_assets():
    assert 'corresponding quantitative tables and plots' in SIMULATION_END_DISCLOSURE
    assert 'Conceptual diagrams and prospective design tables' in SIMULATION_END_DISCLOSURE
    assert 'not simulated observations or evidence that those procedures were executed' in SIMULATION_END_DISCLOSURE


def test_end_disclosure_is_excluded_from_repeated_framing_scan() -> None:
    source = (
        "\\section{Conclusion}\nFinal finding.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        "\\end{document}\n"
    )

    assert rendered_mode_framing_hits(source) == ()
    assert rendered_mode_framing_hits_outside_end_disclosure(source) == ()


def test_visible_prose_ignores_internal_preview_paths_but_finds_rendered_framing() -> None:
    plumbing_only = (
        "\\section{Results}\n"
        "\\input{synthetic_preview_figures}\n"
        "Figure~\\ref{fig:preview-main-comparison} reports the comparison.\n"
        "% synthetic preview is an internal sidecar term\n"
    )
    rendered = (
        plumbing_only
        + "This evidence-calibrated preview summarizes a controlled simulation benchmark.\n"
    )

    assert "synthetic_preview" not in visible_latex_prose(plumbing_only)
    assert rendered_mode_framing_hits(plumbing_only) == ()
    assert set(rendered_mode_framing_hits(rendered)) == {
        "preview",
    }


def test_scientific_simulation_methods_are_not_rejected_as_workflow_framing():
    source = "We simulated fixed-seed observations using synthetic inputs. The simulation does not establish population coverage."
    assert rendered_mode_framing_hits(source) == ()
    assert rendered_mode_framing_hits("This is a synthetic preview awaiting submission eligibility.")
