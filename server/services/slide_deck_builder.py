"""Lifecycle and rendering of contract-grounded Beamer slide sources."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, atomic_write_text
from .slide_text import item_frames, latex


FINDINGS_SYNTHETIC = r"""\begin{frame}{Current Findings}
\begin{itemize}
\item The registered benchmark supports direct quantitative comparison under the declared controls.
\item Every inferential result is paired with an uncertainty interval or uncertainty band.
\item Interpretation remains bounded to the defined evaluation domain, scenario construction, and registered assumptions.
\end{itemize}
\end{frame}"""

LIMITATIONS_SYNTHETIC = r"""\begin{frame}{Limitations}
\begin{itemize}
\item External validity beyond the registered benchmark requires independent evidence.
\item Conclusions depend on the declared study design, independent units, scenario construction, and evaluation endpoints.
\item Failure slices and sensitivity analyses define where the reported ordering may cease to hold.
\end{itemize}
\end{frame}"""

NEXT_SYNTHETIC = r"""\begin{frame}{Next Valid Actions}
\begin{enumerate}
\item Preserve the registered study inputs, metric definitions, and uncertainty records.
\item Extend stress and sensitivity coverage without changing the registered primary contrast.
\item Test external validity with independent evidence where the target claim requires it.
\item Update the paper and slides only when the bound benchmark package changes.
\end{enumerate}
\end{frame}"""

FINDINGS_PENDING = r"""\begin{frame}{Current Findings}
\begin{itemize}
\item The primary interpretation is defined by the prespecified endpoints and matched controls.
\item Uncertainty must be estimated over independent datasets, subjects, tasks, or runs as appropriate.
\item Without measured results, the study yields no quantitative ordering or superiority conclusion.
\end{itemize}
\end{frame}"""

LIMITATIONS_PENDING = r"""\begin{frame}{Limitations}
\begin{itemize}
\item Evidence may be incomplete, dependent, leaked, unfairly tuned, or underpowered.
\item A matched simpler control may explain the intended mechanism.
\item Prior-art coverage and implementation-to-contract alignment remain auditable risks.
\end{itemize}
\end{frame}"""

NEXT_PENDING = r"""\begin{frame}{Next Valid Actions}
\begin{enumerate}
\item Execute the frozen primary comparison and matched controls.
\item Preserve immutable run, split, configuration, prediction, and log provenance.
\item Classify every claim as supported, contradicted, or pending after audit.
\item Update paper and slides without strengthening unresolved claims.
\end{enumerate}
\end{frame}"""

DECK_TEMPLATE = r"""% MERAK_GENERATED_SLIDES
\documentclass[aspectratio=169]{{beamer}}
\usepackage{{graphicx}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usetheme{{default}}
\setbeamertemplate{{navigation symbols}}{{}}
\definecolor{{MerakTeal}}{{HTML}}{{007C83}}
\definecolor{{MerakOrange}}{{HTML}}{{C65D21}}
\setbeamercolor{{structure}}{{fg=MerakTeal}}
\setbeamercolor{{alerted text}}{{fg=MerakOrange}}
\title{{{title}}}
\subtitle{{Scientific study overview}}
\author{{Anonymous Authors}}
\date{{}}
\begin{{document}}
\begin{{frame}}\titlepage\end{{frame}}
\begin{{frame}}{{Problem and Frozen Hypothesis}}
\textbf{{Problem.}} {problem}
\medskip

\textbf{{Hypothesis.}} {hypothesis}
\end{{frame}}
\begin{{frame}}{{Scientific Contribution}}
\begin{{itemize}}
\item The study isolates the declared independent variable under matched comparisons.
\item The proposed mechanisms define measurable, domain-facing endpoints.
\item Null and negative outcomes remain valid scientific conclusions.
\end{{itemize}}
\end{{frame}}
{mechanisms}
{method_figure}
{controls}
{components}
{results}
{questions}
{findings}
{falsification}
{limitations}
{next_actions}
\begin{{frame}}{{Conclusion}}
{conclusion}
\end{{frame}}
\end{{document}}
"""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _owned_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Slide plan is empty or not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Slide plan is unreadable or corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Slide plan root must be a JSON object: {path}")
    return value


def _existing_result(
    service: Any,
    root: Path,
    *,
    force: bool,
    bind_existing: bool,
) -> tuple[dict[str, Any] | None, bool]:
    main = root / "slides" / "main.tex"
    plan_path = root / "slides" / "SLIDE_PLAN.json"
    if not main.is_file() or main.stat().st_size <= 0 or force:
        return None, force
    current = main.read_text(encoding="utf-8-sig", errors="replace")
    if not current.lstrip().startswith("% MERAK_GENERATED_SLIDES"):
        result = service.bind_existing(root) if bind_existing else {
            "generated": False, "path": str(main), "plan_path": "",
        }
        return result, False
    source_hash, _ = service.source_bundle(root)
    plan = _owned_json(plan_path)
    current_hash = hashlib.sha256(main.read_bytes()).hexdigest()
    if plan.get("source_bundle_sha256") == source_hash and plan.get("tex_sha256") == current_hash:
        return {
            "generated": False, "path": str(main), "plan_path": str(plan_path),
        }, False
    return None, True


def _backup_existing(root: Path, force: bool) -> None:
    main = root / "slides" / "main.tex"
    if not force or not main.is_file() or main.stat().st_size <= 0:
        return
    digest = hashlib.sha256(main.read_bytes()).hexdigest()[:10]
    backup = root / "slides" / "revisions" / f"previous_slides_{digest}.tex"
    if not backup.exists():
        atomic_write_bytes(backup, main.read_bytes())


def _context(service: Any, root: Path, direction: str) -> dict[str, Any]:
    selected = _json(root / "ideas" / "SELECTED_IDEA.json")
    method = _json(root / "experiments" / "METHOD_CONTRACT.json")
    assets = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    manifest = _json(root / "figures" / "FIGURE_MANIFEST.json")
    figures, synthetic = service._deck_figures(root, assets, manifest)
    evaluation = method.get("evaluation_contract")
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    mode = str(assets.get("evidence_mode") or "planned")
    return {
        "root": root,
        "title": str(selected.get("title") or direction or "Research Project"),
        "problem": str(selected.get("problem_statement") or "A frozen scientific problem defines this project."),
        "hypothesis": str(selected.get("hypothesis") or "The selected mechanism has a testable consequence."),
        "claims": [item for item in selected.get("claims") or [] if isinstance(item, dict)],
        "mechanisms": [item for item in selected.get("mechanisms") or [] if isinstance(item, dict) and item.get("required", True)],
        "failures": [str(item) for item in selected.get("falsification_conditions") or []],
        "controls": [str(item) for item in evaluation.get("comparators_or_controls") or []],
        "component_tests": [str(item) for item in evaluation.get("component_tests") or []],
        "declared_family": " ".join((
            str(method.get("study_archetype") or ""),
            str(method.get("research_family") or ""),
            str((assets.get("method_brief") or {}).get("study_archetype") or ""),
        )).casefold(),
        "evidence_mode": mode,
        "simulation_mode": mode.casefold() == "synthetic_preview",
        "figures": figures,
        "synthetic_figures": synthetic,
    }


def _figure_frame(title: str, item: dict[str, Any] | None) -> str:
    if not item:
        return rf"""\begin{{frame}}{{{latex(title)}}}
\begin{{itemize}}
\item No paper-selected scientific figure is available for this role.
\item The missing asset remains an explicit evidence gap.
\end{{itemize}}
\end{{frame}}"""
    from .slide_presentation_projection import presentation_output_path

    path = "../" + presentation_output_path(item).replace("\\", "/")
    caption = str((item.get("metadata") or {}).get("scientific_question") or item.get("caption") or "Scientific asset")
    caption = re.sub(r"(?<![A-Za-z0-9])(?:C|M|F|I)\d+(?![A-Za-z0-9])", "the declared mechanism", caption)
    return rf"""\begin{{frame}}{{{latex(title)}}}
\centering
\includegraphics[width=0.94\linewidth,height=0.72\textheight,keepaspectratio]{{{path}}}
\par\smallskip
\footnotesize {latex(caption, 240)}
\end{{frame}}"""


def _default_controls(family: str) -> tuple[list[str], list[str]]:
    if any(term in family for term in ("formal", "proof", "theory")):
        return ["Weaken or remove each essential assumption", "Construct boundary cases and counterexamples", "Compare against the nearest known guarantee"], ["Assumption-necessity analysis", "Proof-step dependency check", "Tightness or counterexample analysis"]
    if any(term in family for term in ("qualitative", "mixed")):
        return ["Independent coding or adjudication", "Negative and divergent case search", "Source and investigator triangulation"], ["Coding-framework sensitivity", "Saturation and sampling sensitivity", "Theme stability under alternate interpretations"]
    if any(term in family for term in ("clinical", "trial", "cohort", "diagnostic")):
        return ["Prespecified comparator or reference standard", "Confounding and missingness adjustment", "Site, subgroup, and protocol sensitivity"], ["Estimand and covariate sensitivity", "Missing-data analysis", "Subgroup consistency and influence analysis"]
    if any(term in family for term in ("systems", "simulation", "controlled_experiment", "omics")):
        return ["Reference configuration under matched conditions", "Scale, workload, or operating-range control", "Independent replication and uncertainty accounting"], ["Factor or subsystem removal", "Operating-range sensitivity", "Failure-mode and resource analysis"]
    return ["Nearest verified prior method", "Simple domain baseline", "Matched-resource control"], ["Remove the required mechanism", "Matched alternative explanation", "Sensitivity to the primary design choices"]


def _selected_figures(context: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    figures = context["figures"]
    method = next(
        (item for item in figures if (item.get("metadata") or {}).get("scientific_role") == "method"),
        figures[0] if figures else None,
    )
    if context["simulation_mode"]:
        return method, context["synthetic_figures"]
    result = next((
        item for item in figures
        if (item.get("metadata") or {}).get("scientific_role")
        in {"result", "ablation", "robustness", "analysis", "qualitative"}
    ), figures[1] if len(figures) > 1 else None)
    return method, [result] if result else []


def _result_sections(
    context: dict[str, Any],
    results: list[dict[str, Any]],
    figure_titles: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    if context["simulation_mode"]:
        by_id = {
            str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""): item
            for item in results
        }
        frames = "\n\n".join(
            _figure_frame(title, item)
            for identity, title in figure_titles
            if (item := by_id.get(identity)) is not None
        )
        conclusion = "Within the registered benchmark, the contribution-selected evidence addresses the declared scientific questions under the matched controls and registered assumptions."
        return {"frames": frames, "findings": FINDINGS_SYNTHETIC, "limitations": LIMITATIONS_SYNTHETIC, "next": NEXT_SYNTHETIC, "conclusion": conclusion}
    frames = _figure_frame("Quantitative or Qualitative Analysis", results[0]) if results else ""
    conclusion = "The study defines a testable hypothesis, domain-specific mechanisms, controlled comparisons, and interpretable positive and negative outcomes."
    return {"frames": frames, "findings": FINDINGS_PENDING, "limitations": LIMITATIONS_PENDING, "next": NEXT_PENDING, "conclusion": conclusion}


def _render(
    context: dict[str, Any],
    method_figure: dict[str, Any] | None,
    result_figures: list[dict[str, Any]],
    figure_titles: tuple[tuple[str, str], ...],
) -> str:
    default_controls, default_components = _default_controls(context["declared_family"])
    mechanisms = [
        f"{item.get('name')} - {item.get('description')}" for item in context["mechanisms"]
    ] or ["The required mechanism is not yet available in the frozen contract."]
    questions = [str(item.get("statement") or "") for item in context["claims"]] or [
        "The central scientific hypothesis is evaluated within the registered benchmark."
        if context["simulation_mode"] else "The central scientific hypothesis requires empirical evaluation."
    ]
    failures = [re.sub(r"^(?:F|C|M|I)\d+\s*:\s*", "", item) for item in context["failures"][:5]] or ["The strongest matched control explains the effect."]
    result = _result_sections(context, result_figures, figure_titles)
    return DECK_TEMPLATE.format(
        title=latex(context["title"], 500), problem=latex(context["problem"], 260),
        hypothesis=latex(context["hypothesis"], 260),
        mechanisms=item_frames("Required Mechanisms", mechanisms, per_frame=3, item_limit=135),
        method_figure=_figure_frame("Method Architecture", method_figure),
        controls=item_frames("Matched Controls", context["controls"] or default_controls, per_frame=4, item_limit=125),
        components=item_frames("Component Tests", context["component_tests"] or default_components, per_frame=4, item_limit=125),
        results=result["frames"], questions=item_frames("Research Questions", questions, per_frame=3, item_limit=135),
        findings=result["findings"], falsification=item_frames("Falsification and Pivot Conditions", failures, per_frame=3, item_limit=135),
        limitations=result["limitations"], next_actions=result["next"],
        conclusion=latex(result["conclusion"], 500),
    )


def _persist(
    service: Any,
    root: Path,
    context: dict[str, Any],
    text: str,
    method_figure: dict[str, Any] | None,
    result_figures: list[dict[str, Any]],
) -> dict[str, Any]:
    slides = root / "slides"
    main = slides / "main.tex"
    plan_path = slides / "SLIDE_PLAN.json"
    slides.mkdir(parents=True, exist_ok=True)
    atomic_write_text(main, text)
    source_hash, sources = service.source_bundle(root)
    selected = ([method_figure] if method_figure else []) + result_figures
    atomic_write_json(plan_path, {
        "schema": 1, "generated_at": time.time(),
        "generator": "deterministic:contract-grounded-beamer",
        "evidence_mode": context["evidence_mode"],
        "source_bundle_sha256": source_hash,
        "sources": [source.relative_to(root).as_posix() if source.is_relative_to(root) else source.as_posix() for source in sources],
        "tex_sha256": hashlib.sha256(main.read_bytes()).hexdigest(),
        "selected_figures": [str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or "") for item in selected],
    })
    return {"generated": True, "path": str(main), "plan_path": str(plan_path), "evidence_mode": context["evidence_mode"]}


def ensure_slide_deck(
    service: Any,
    project_path: str | Path,
    research_direction: str,
    *,
    force: bool,
    bind_existing: bool,
    figure_titles: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    early, force = _existing_result(
        service, root, force=force, bind_existing=bind_existing
    )
    if early is not None:
        return early
    _backup_existing(root, force)
    context = _context(service, root, research_direction)
    method, results = _selected_figures(context)
    return _persist(
        service, root, context,
        _render(context, method, results, figure_titles), method, results,
    )
