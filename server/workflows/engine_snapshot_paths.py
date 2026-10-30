"""Resolve the artifact closure inspected by accepted workflow gates."""

from .engine_context import *  # noqa: F403, F405
from .artifact_snapshot_ownership import owner_snapshot_paths


def accepted_snapshot_paths(
    engine: Any, run: WorkflowRun, node_id: str, gate: dict[str, Any],
    requirements: list[Path],
) -> list[Path]:
    root = Path(run.project_path).expanduser().resolve()
    paths = list(requirements)
    details = gate.get("details")
    details = details if isinstance(details, dict) else {}
    if node_id in {"lit", "idea", "novelty", "exp-design", "exp-run"}:
        _early_stage(paths, root, run, node_id)
    elif node_id == "figure":
        _figure_paths(engine, paths, root)
    elif node_id == "results":
        paths = _result_paths(engine, paths, root, run)
    elif node_id == "narrative":
        _narrative_paths(engine, paths, root)
    elif node_id == "paper":
        _paper_paths(engine, paths, root, details)
    elif node_id in {"review", "audit", "compile", "ppt"}:
        _downstream_paths(engine, paths, root, node_id)
    return _unique(owner_snapshot_paths(root, node_id, paths))


def _early_stage(
    paths: list[Path], root: Path, run: WorkflowRun, node_id: str,
) -> None:
    additions = {
        "lit": [root / ".merak/research_strategy.json", root / "literature/SEARCH_EVIDENCE.json"],
        "idea": [root / "literature/survey.md", root / "literature/references.bib"],
        "novelty": [root / ".merak/research_strategy.json", root / "literature/SEARCH_EVIDENCE.json", root / "literature/references.bib", root / "ideas/ideas.md"],
        "exp-design": [root / "ideas/SELECTED_IDEA.json"],
    }
    paths.extend(additions.get(node_id, []))
    if node_id == "exp-run" and run.options.get("run_experiment") is not True:
        # Planned execution artifacts still depend on the accepted method and
        # implementation/configuration. Skipping compute does not remove that
        # dependency or permit reuse after upstream source changes.
        paths.extend([
            root / "experiments/RUN_SPEC.json",
            root / "experiments/METHOD_CONTRACT.json",
            root / "experiments/src",
            root / "experiments/configs",
            root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json",
        ])


def _figure_paths(engine: Any, paths: list[Path], root: Path) -> None:
    paths.append(root / "paper/PAPER_PLAN.md")
    for relative in (
        "figures/SCIENTIFIC_ASSET_PLAN.json", "figures/FIGURE_SPECS.json",
        "figures/FIGURE_MANIFEST.json",
    ):
        path = root / relative
        paths.extend(engine._manifest_dependency_paths(root, _read_json(path)))


def _result_paths(
    engine: Any, paths: list[Path], root: Path, run: WorkflowRun,
) -> list[Path]:
    results = root / "experiments/results"
    mode = str(run.options.get("non_experiment_evidence_mode") or "design_only").strip().casefold()
    # Imported and secondary-analysis evidence is empirical input even when
    # this run has no permission to execute an experiment. Bind its data and
    # provenance just as strictly; never infer execution authorization from it.
    if run.options.get("run_experiment") is True or mode in {"existing_results", "secondary_analysis"}:
        paths.extend([results, root / "experiments/RUN_SPEC.json", root / "ideas/SELECTED_IDEA.json"])
        runtime = root / ".merak/experiments"
        if runtime.is_dir():
            paths.extend(runtime.glob("*/run.json"))
        return paths
    paths = [path for path in paths if path.expanduser().resolve() != results.resolve()]
    common = [root / "experiments/results/analysis.md", root / "experiments/RUN_SPEC.json", root / "ideas/SELECTED_IDEA.json"]
    if mode != "synthetic_preview":
        return [*paths, *common, root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"]
    manifest_path = results / "simulated/SIMULATION_MANIFEST.json"
    manifest = _read_json(manifest_path)
    paths.extend([*common, manifest_path])
    for item in manifest.get("data_files") or []:
        if isinstance(item, dict):
            candidate = engine._project_artifact_reference(root, item.get("path"))
            if candidate is not None:
                paths.append(candidate)
    return paths


def _narrative_paths(engine: Any, paths: list[Path], root: Path) -> None:
    build_path = root / ".merak/NARRATIVE_BUILD.json"
    paths.extend([
        build_path, root / "ideas/SELECTED_IDEA.json",
        root / "experiments/METHOD_CONTRACT.json",
        root / "experiments/results/analysis.md", root / "literature/survey.md",
    ])
    paths.extend(engine._manifest_dependency_paths(root, _read_json(build_path)))


def _paper_paths(
    engine: Any, paths: list[Path], root: Path, details: dict[str, Any],
) -> None:
    from ..services.latex_bundle import latex_source_bundle
    paths.extend(latex_source_bundle(root / "paper")[1])
    table_manifest = root / "paper/tables/TABLE_MANIFEST.json"
    paths.extend(engine._manifest_dependency_paths(root, _read_json(table_manifest)))
    for key in ("sources", "graphics"):
        for raw in details.get(key) or []:
            candidate = engine._project_artifact_reference(root, raw)
            if candidate is not None:
                paths.append(candidate)
    for relative in (
        "figures/SCIENTIFIC_ASSET_PLAN.json", "figures/FIGURE_MANIFEST.json",
        "ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json",
        "experiments/RUN_SPEC.json", "experiments/results/analysis.md",
        "experiments/results/reference_baseline/metrics.json",
        "experiments/results/proposed_method/metrics.json", "literature/references.bib",
        "NARRATIVE_REPORT.md", "paper/PAPER_PLAN.md", "paper/PAPER_BUDGET.json",
        "paper/PAPER_PROFILE.json", "paper/SCIENTIFIC_FREEZE.json",
    ):
        candidate = root / relative
        if candidate.exists():
            paths.append(candidate)


def _downstream_paths(
    engine: Any, paths: list[Path], root: Path, node_id: str,
) -> None:
    from ..services.latex_bundle import latex_source_bundle
    paths.extend(latex_source_bundle(root / "paper")[1])
    if node_id == "review":
        _review_paths(engine, paths, root)
    elif node_id == "audit":
        _audit_paths(engine, paths, root)
    elif node_id == "compile":
        build = root / "paper/PAPER_BUILD.json"
        paths.extend(engine._manifest_dependency_paths(root, _read_json(build)))
        if (root / "paper/main.log").exists():
            paths.append(root / "paper/main.log")
    else:
        _slide_paths(engine, paths, root, latex_source_bundle)


def _review_paths(engine: Any, paths: list[Path], root: Path) -> None:
    from .review_audit import review_source_bundle
    paths.extend(review_source_bundle(root)[1])
    state = root / "review-stage/REVIEW_STATE.json"
    paths.extend([root / "paper/main.pdf", state])
    paths.extend(engine._manifest_dependency_paths(root, _read_json(state)))


def _audit_paths(engine: Any, paths: list[Path], root: Path) -> None:
    from .review_audit import audit_source_bundle
    paths.extend(audit_source_bundle(root)[1])
    paths.extend([root / "experiments/RUN_SPEC.json", root / "experiments/results"])
    for record in (
        root / "audit-results/AUDIT_RESULTS.json",
        root / "audit-results/AUDIT_BUILD.json", root / "paper/PROOF_AUDIT.json",
    ):
        paths.extend(engine._manifest_dependency_paths(root, _read_json(record)))


def _slide_paths(engine: Any, paths: list[Path], root: Path, bundle: Any) -> None:
    paths.extend(bundle(root / "slides")[1])
    manifest = root / "figures/FIGURE_MANIFEST.json"
    if manifest.is_file():
        paths.append(manifest)
        paths.extend(engine._manifest_dependency_paths(root, _read_json(manifest)))
    if (root / "slides/main.log").exists():
        paths.append(root / "slides/main.log")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _unique(paths: list[Path]) -> list[Path]:
    unique, seen = [], set()
    for path in paths:
        resolved = path.expanduser().resolve()
        marker = str(resolved).casefold()
        if marker not in seen:
            seen.add(marker)
            unique.append(resolved)
    return unique
