"""Conservative augmentation of an existing substantive manuscript."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ..utils.atomic_write import atomic_write_text
from .paper_evidence import PaperEvidence, _read

_PLACEHOLDER_SIGNAL = re.compile(
    r"(?:lorem ipsum|your paper title|your abstract here|todo\b|placeholder|"
    r"insert (?:text|figure|table)|待补充|此处填写)",
    re.IGNORECASE,
)
_RESULT_ROLES = frozenset({
    "result", "ablation", "robustness", "analysis", "efficiency",
    "calibration", "error_analysis", "sensitivity", "training_dynamics",
})
_EVALUATION_ROLES = frozenset({"evaluation_design", "dataset", "data", "study_overview"})


def augment_existing_manuscript(
    evidence: PaperEvidence, backup_main: Callable[[Path], None]
) -> bool:
    main_path = evidence.root / "paper" / "main.tex"
    content = _read(main_path, 250000)
    if not _is_substantive_document(content):
        return False
    content, changed = _ensure_packages(content)
    groups = _figure_groups(evidence)
    content, figures_changed = _add_figure_bundles(content, groups)
    content, tables_changed = _add_table_bundles(content, evidence)
    content, citations_changed = _add_citations(content, evidence)
    if not any((changed, figures_changed, tables_changed, citations_changed)):
        return False
    backup_main(main_path)
    atomic_write_text(main_path, content)
    return True


def _is_substantive_document(content: str) -> bool:
    return bool(
        len(content) >= 2500
        and "\\documentclass" in content
        and "\\begin{document}" in content
        and "\\end{document}" in content
        and not _PLACEHOLDER_SIGNAL.search(content)
    )


def _ensure_packages(content: str) -> tuple[str, bool]:
    packages = [
        package
        for package in ("graphicx", "booktabs", "tabularx")
        if not re.search(
            rf"\\usepackage(?:\[[^\]]*\])?\{{[^}}]*\b{package}\b[^}}]*\}}",
            content,
        )
    ]
    if not packages:
        return content, False
    match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", content)
    if not match:
        return content, False
    insertion = "\n".join(rf"\usepackage{{{package}}}" for package in packages)
    return content[:match.end()] + "\n" + insertion + content[match.end():], True


def _figure_groups(evidence: PaperEvidence) -> dict[str, list[dict[str, object]]]:
    result: list[dict[str, object]] = []
    evaluation: list[dict[str, object]] = []
    method: list[dict[str, object]] = []
    for item in evidence.figures:
        role = str((item.get("metadata") or {}).get("scientific_role") or "").casefold()
        if role in _RESULT_ROLES:
            result.append(item)
        elif role in _EVALUATION_ROLES:
            evaluation.append(item)
        else:
            method.append(item)
    return {"method": method, "evaluation": evaluation, "result": result}


def _add_figure_bundles(
    content: str, groups: dict[str, list[dict[str, object]]]
) -> tuple[str, bool]:
    changed = False
    if (groups["method"] and "\\input{generated_method_figures}" not in content
            and not re.search(r"\\begin\{figure\*?\}", content)):
        label = _first_label(groups["method"], "fig:method-architecture")
        content = _insert_before_section(
            content, "experiment|evaluation|result|实验|结果",
            rf"\paragraph{{Method overview.}} Figure~\ref{{{label}}} summarizes the "
            "domain-specific components and information flow.\n\n"
            r"\input{generated_method_figures}",
        )
        changed = True
    if groups["evaluation"] and "\\input{generated_evaluation_figures}" not in content:
        label = _first_label(groups["evaluation"], "fig:evaluation-design")
        content = _insert_before_section(
            content, "result|discussion|结果|讨论",
            rf"\paragraph{{Evaluation design.}} Figure~\ref{{{label}}} defines the "
            "isolated data partitions, held-out conditions, endpoints, and uncertainty units.\n\n"
            r"\input{generated_evaluation_figures}",
        )
        changed = True
    content, result_changed = _add_result_figures(content, groups["result"])
    return content, changed or result_changed


def _add_result_figures(
    content: str, figures: list[dict[str, object]]
) -> tuple[str, bool]:
    figures = [
        item for item in figures
        if str((item.get("metadata") or {}).get("label") or "") not in content
        and str(item.get("paper_path") or "") not in content
    ]
    if not figures or "\\input{generated_result_figures}" in content:
        return content, False
    references = ", ".join(
        rf"Figure~\ref{{{label}}}"
        for item in figures
        for label in [str((item.get("metadata") or {}).get("label") or "")]
        if label.startswith("fig:")
    )
    addition = (
        f"{references or 'The result figures'} report the registered comparison "
        "and uncertainty encoding.\n\n" + r"\input{generated_result_figures}"
    )
    return _insert_before_section(content, "discussion|limitation|讨论|局限", addition), True


def _add_table_bundles(
    content: str, evidence: PaperEvidence
) -> tuple[str, bool]:
    additions = []
    if "\\input{tables/study_design}" not in content:
        additions.append((
            "result|discussion|结果|讨论",
            r"\paragraph{Evaluation dimensions.} Table~\ref{tab:study-design} summarizes "
            r"the controlled factors used to separate model, data, and condition effects."
            "\n\n" r"\input{tables/study_design}",
        ))
    if (len(re.findall(r"\\begin\{table\*?\}", content)) < 2
            and "\\input{tables/method_components}" not in content):
        additions.append((
            "experiment|evaluation|result|实验|结果",
            r"\paragraph{Component-level evaluation.} Table~\ref{tab:method-components} "
            r"states each component's scientific function and decisive comparison."
            "\n\n" r"\input{tables/method_components}",
        ))
    result_table = evidence.root / "paper" / "tables" / "main_results.tex"
    if (not evidence.experiments_pending and result_table.is_file()
            and "\\input{tables/main_results}" not in content):
        additions.append((
            "discussion|limitation|讨论|局限",
            r"Table~\ref{tab:main-results} reports the primary comparison with run-level "
            r"uncertainty."
            "\n\n" r"\input{tables/main_results}",
        ))
    for section, addition in additions:
        content = _insert_before_section(content, section, addition)
    return content, bool(additions)


def _add_citations(content: str, evidence: PaperEvidence) -> tuple[str, bool]:
    keys = [entry.key for entry in evidence.bib_entries[:5] if entry.key]
    if not keys or re.search(r"\\cite[a-zA-Z*]*\{", content):
        return content, False
    addition = "Prior work motivating the problem setting includes " + rf"\cite{{{','.join(keys)}}}."
    return _insert_before_section(content, "method|approach|方法", addition), True


def _first_label(figures: list[dict[str, object]], fallback: str) -> str:
    return str((figures[0].get("metadata") or {}).get("label") or fallback)


def _insert_before_section(source: str, names: str, addition: str) -> str:
    match = re.search(
        rf"\\section\*?\{{[^}}]*(?:{names})[^}}]*\}}", source, flags=re.IGNORECASE
    )
    if match:
        return source[:match.start()] + addition + "\n\n" + source[match.start():]
    return source.replace("\\end{document}", addition + "\n\n\\end{document}", 1)
