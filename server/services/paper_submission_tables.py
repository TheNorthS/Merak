"""Build publication tables and their provenance manifest."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from .paper_evidence import (
    PaperEvidence,
    _read,
    _table_source_matches_registered_rows,
)
from .paper_table_projection import (
    method_components_table_tex,
    project_result_table_rows,
    public_results_table_tex,
    study_design_table_tex,
    write_csv,
)
from .publication_labels import publication_metric_label
from .run_spec import execution_seeds


def write_submission_tables(evidence: PaperEvidence) -> None:
    """Prepare every public table before committing the complete canonical bundle."""
    from .paper_table_transaction import commit_prepared_table_bundle

    sources = _contract_sources(evidence.root)
    from .paper_table_transaction import _read_current_manifest
    existing_manifest = _read_current_manifest(evidence.root / "paper/tables/TABLE_MANIFEST.json")
    source_hashes = _table_input_hashes(evidence.root, sources)
    for entry in existing_manifest.get("tables") or []:
        relative = str(entry.get("data_path") or "")
        path = (evidence.root / relative).resolve()
        if relative and path.is_relative_to(evidence.root) and path.is_file() and not relative.startswith("paper/tables/"):
            source_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical_baseline = {path.relative_to(evidence.root).as_posix(): path.read_bytes()
                          for directory in (evidence.root / "paper/tables", evidence.root / ".merak/paper-table-records")
                          for path in directory.glob("*") if path.is_file()}
    from .simulation_table_publication import prepare_simulation_table_publication
    simulation_update = prepare_simulation_table_publication(evidence.root, str(
        (evidence.selected_idea.get("publication") or {}).get("contribution_type") or "",
    )) if evidence.synthetic_preview else None
    if simulation_update is not None:
        source_hashes.update(simulation_update.source_hashes)
        canonical_baseline.update({relative: (evidence.root / relative).read_bytes()
                                   for relative in simulation_update.files if (evidence.root / relative).is_file()})
    study_rows = _study_rows(evidence)
    component_rows, publication_rows = _component_rows(evidence)
    _reject_unbound_existing_design_sources(evidence.root, study_rows, publication_rows)
    transactions = evidence.root / ".merak" / "transactions"
    transactions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publication-tables-", dir=transactions) as directory:
        stage = Path(directory)
        table_dir = stage / "paper" / "tables"
        table_dir.mkdir(parents=True)
        _copy_reviewed_table_sources(evidence.root, table_dir)
        if simulation_update is not None:
            from ..utils.atomic_write import atomic_write_bytes
            for relative, content in simulation_update.files.items():
                atomic_write_bytes(stage / relative, content)
        manifest = _write_design_tables(
            table_dir, study_rows, component_rows, publication_rows, sources,
            source_hashes=source_hashes, evidence=evidence,
        )
        manifest.extend(_write_executed_tables(evidence, table_dir))
        manifest.extend(_synthetic_preview_entries(evidence, table_dir))
        owned = {entry[key] for entry in manifest if entry["evidence_status"] != "synthetic_preview"
                 for key in ("data_path", "latex_path")}
        owned.update(path.relative_to(stage).as_posix() for path in (stage / ".merak/paper-table-records").glob("*") if path.is_file())
        owned.update("paper/tables/" + name for name in ("study_design.tex", "method_components.tex")
                     if (table_dir / name).is_file())
        if simulation_update is not None:
            owned.update(simulation_update.files)
        commit_prepared_table_bundle(evidence.root, stage, manifest, source_hashes=source_hashes,
                                     owned_paths=owned, canonical_baseline=canonical_baseline)


def _copy_reviewed_table_sources(root: Path, target: Path) -> None:
    """Keep source-only reviewed layouts eligible; they still bind exact public rows."""
    for path in (root / "paper" / "tables").glob("*.tex"):
        shutil.copy2(path, target / path.name)


def _reject_unbound_existing_design_sources(
    root: Path, study_rows: list[dict[str, str]], component_rows: list[dict[str, str]],
) -> None:
    for name, rows in (("study_design", study_rows), ("method_components", component_rows)):
        path = root / f"paper/tables/{name}.tex"
        if not rows and path.is_file() and path.stat().st_size > 0:
            raise ValueError(f"{name}: existing public source has no current authored design records; "
                             "the producer will not reuse or delete unbound scientific text")


def _table_input_hashes(root: Path, sources: list[str]) -> dict[str, str]:
    paths = [root / relative for relative in sources]
    paths.extend((root / "experiments/results/aggregates").glob("*.csv"))
    selection = root / 'experiments/results/accepted_matrix.json'
    if selection.is_file():
        paths.append(selection)
        spec = json.loads((root / 'experiments/RUN_SPEC.json').read_text(encoding='utf8'))
        for relative in (spec.get('outputs') or {}).get('aggregate_files', []):
            path = (root / relative).resolve()
            if not path.is_relative_to(root / 'experiments/results'):
                raise ValueError('Registered table input leaves project results')
            paths.append(path)
    paths.extend((root / "experiments/results/simulated").glob("*.csv"))
    preview = root / "paper/tables/synthetic_preview_results.tex"
    if preview.is_file():
        paths.append(preview)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def _contract_sources(root: Path) -> list[str]:
    return [
        relative
        for relative in (
            "ideas/SELECTED_IDEA.json",
            "experiments/RUN_SPEC.json",
            "experiments/METHOD_CONTRACT.json",
            "experiments/configs/main.yaml",
            "paper/METHOD_TABLE_PRESENTATION.json",
            "paper/sections/03_method.tex",
            "paper/sections/04_experiments.tex",
        )
        if (root / relative).is_file() and (root / relative).stat().st_size > 0
    ]


def _clean_values(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(str(item).replace("_", " ").split())
        for item in value[:limit]
        if str(item).strip()
    ]


def _study_rows(evidence: PaperEvidence) -> list[dict[str, str]]:
    run_spec = evidence.run_spec
    config = evidence.resolved_config
    experiment = _mapping(config, "experiment")
    evaluation = _mapping(config, "evaluation")
    statistics = _mapping(config, "statistics")
    data_config = _mapping(config, "data")
    method_config = _mapping(config, "method")
    matrix = _mapping(run_spec, "matrix")
    seeds = statistics.get("seeds") or execution_seeds(run_spec)
    dimensions = _base_dimensions(run_spec, matrix, data_config, method_config, seeds)
    dimensions.extend(_budget_dimensions(config, run_spec))
    dimensions.extend(_measurement_dimensions(method_config, run_spec))
    primary = str(
        experiment.get("primary_metric")
        or run_spec.get("primary_metric")
        or evaluation.get("primary_metric")
        or ""
    ).strip()
    if primary:
        dimensions.append((
            "Primary endpoint",
            [publication_metric_label(primary)],
            "Main statistical comparison",
        ))
    return [
        {"dimension": name, "setting": "; ".join(values), "purpose": purpose}
        for name, values, purpose in dimensions
        if values
    ]


def _mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def _base_dimensions(
    run_spec: dict[str, Any],
    matrix: dict[str, Any],
    data_config: dict[str, Any],
    method_config: dict[str, Any],
    seeds: Any,
) -> list[tuple[str, list[str], str]]:
    return [
        (
            "Candidate models",
            _clean_values(run_spec.get("models") or matrix.get("models") or method_config.get("model_suite")),
            "Model ranking or matched comparison",
        ),
        ("Datasets", _clean_values(run_spec.get("datasets")), "Cross-cohort and task generalization"),
        ("Tasks", _clean_values(run_spec.get("tasks")), "Declared downstream evaluation"),
        (
            "Study conditions",
            _clean_values(run_spec.get("adaptation_regimes") or matrix.get("protocol_conditions")),
            "Controlled independent variable",
        ),
        (
            "Protected partitions",
            _clean_values(matrix.get("final_partitions") or data_config.get("partitions")),
            "Leakage-safe fitting, calibration, and final evaluation",
        ),
        ("Random seeds", _clean_values(seeds), "Run-level uncertainty and paired comparison"),
    ]


def _budget_dimensions(
    config: dict[str, Any], run_spec: dict[str, Any]
) -> list[tuple[str, list[str], str]]:
    execution = _mapping(config, "execution")
    resources = _mapping(run_spec, "resources")
    max_epochs = execution.get("max_epochs") or resources.get("max_epochs_per_run")
    tuning = execution.get("tuning_trials_per_model_protocol")
    if tuning is None:
        tuning = resources.get("hyperparameter_trials_per_model_protocol")
    parts = []
    if max_epochs is not None:
        parts.append(f"{max_epochs} epochs per run")
    if tuning is not None:
        parts.append(f"{tuning} tuning trials per model/protocol")
    return [(
        "Training and tuning budget",
        parts,
        "Equal optimization opportunity across methods",
    )] if parts else []


def _measurement_dimensions(
    method: dict[str, Any], run_spec: dict[str, Any]
) -> list[tuple[str, list[str], str]]:
    dimensions: list[tuple[str, list[str], str]] = []
    calibration = _mapping(method, "calibration")
    if calibration:
        values = [
            str(calibration.get("method") or "").replace("_", " "),
            "fit on " + str(calibration.get("fit_partition") or "").replace("_", " "),
        ]
        dimensions.append((
            "Calibration protocol",
            [item for item in values if item.strip() not in {"", "fit on"}],
            "Keep probability calibration isolated from final test data",
        ))
    dimensions.extend(_compute_measurement_dimension(method, run_spec))
    return dimensions


def _compute_measurement_dimension(
    method: dict[str, Any], run_spec: dict[str, Any]
) -> list[tuple[str, list[str], str]]:
    efficiency = _mapping(method, "efficiency_measurement")
    resources = _mapping(run_spec, "resources")
    environment = _mapping(run_spec, "environment")
    warmup = efficiency.get("warmup_iterations") or resources.get("efficiency_warmup_iterations")
    repetitions = efficiency.get("measured_iterations") or resources.get("efficiency_measured_iterations")
    values = [
        f"precision {efficiency.get('precision')}" if efficiency.get("precision") else "",
        f"batch size {efficiency.get('batch_size')}" if efficiency.get("batch_size") is not None else "",
        f"{warmup} warm-up iterations" if warmup is not None else "",
        f"{repetitions} measured iterations" if repetitions is not None else "",
    ]
    values = [item for item in values if item]
    values.extend(_clean_values(environment.get("required_runtime_facts"), limit=5))
    return [(
        "Compute measurement contract",
        values,
        "Comparable latency, throughput, memory, and energy accounting",
    )] if values else []


def _component_rows(
    evidence: PaperEvidence,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    plans = {
        str(item.get("idea_claim_id") or ""): item
        for item in evidence.method_contract.get("claim_evidence_plan", [])
        if isinstance(item, dict)
    }
    claims = [item for item in evidence.selected_idea.get("claims", []) if isinstance(item, dict)]
    internal: list[dict[str, str]] = []
    public: list[dict[str, str]] = []
    for index, mechanism in enumerate(evidence.selected_idea.get("mechanisms", [])):
        if not isinstance(mechanism, dict):
            raise ValueError("Method components require authored public mechanism records")
        for field in ("publication_name", "publication_description", "publication_evaluation"):
            if not isinstance(mechanism.get(field), str) or not mechanism[field].strip():
                raise ValueError(f"Method component {index + 1} is missing {field}")
        evaluation = _mechanism_evaluation(mechanism, index, claims, plans)
        name = str(mechanism.get("name") or mechanism["publication_name"]).strip()
        internal.append({
            "component": name,
            "function": str(mechanism.get("description") or "").strip(),
            "evaluation": evaluation,
        })
        public.append(_public_component_row(mechanism, index, evaluation))
    if internal:
        from .method_table_presentation import current_method_rows
        return internal, current_method_rows(evidence.root, public)
    return [], []


def _mechanism_evaluation(
    mechanism: dict[str, Any],
    index: int,
    claims: list[dict[str, Any]],
    plans: dict[str, dict[str, Any]],
) -> str:
    published = str(mechanism.get("publication_evaluation") or "").strip()
    if published:
        return published
    ids = list(mechanism.get("supports_claims") or [])
    if not ids and index < len(claims):
        ids = [claims[index].get("id")]
    outcomes = [
        str(outcome).strip()
        for claim_id in ids
        for outcome in plans.get(str(claim_id), {}).get("outcomes", [])[:1]
        if str(outcome).strip()
    ]
    return outcomes[0] if outcomes else "Matched removal or alternative-mechanism comparison"


def _public_component_row(
    mechanism: dict[str, Any], index: int, evaluation: str
) -> dict[str, str]:
    safe_evaluation = str(mechanism['publication_evaluation']).strip()
    return {
        "component": str(mechanism["publication_name"]).strip(),
        "function": str(mechanism["publication_description"]).strip(),
        "evaluation": safe_evaluation,
    }


def _write_design_tables(
    table_dir: Path,
    study_rows: list[dict[str, str]],
    component_rows: list[dict[str, str]],
    publication_rows: list[dict[str, str]],
    sources: list[str],
    *, source_hashes: dict[str, str], evidence: PaperEvidence,
) -> list[dict[str, Any]]:
    from .paper_table_projection import METHOD_ELEMENTS_CAPTION
    component_caption = METHOD_ELEMENTS_CAPTION
    entries: list[dict[str, Any]] = []
    from .publication_design_prose import design_records_prose

    if study_rows and len(study_rows) < 3:
        atomic_write_text(table_dir / "study_design.tex", design_records_prose(study_rows, identity_key="dimension"))
    if component_rows:
        atomic_write_json(table_dir.parents[1] / ".merak/paper-table-records/method_components.json",
                          {"schema": 1, "records": component_rows})
    if len(publication_rows) == 1:
        atomic_write_text(table_dir / "method_components.tex", design_records_prose(publication_rows, identity_key="component"))
    if len(study_rows) >= 3:
        projection = _design_projection("study_design", study_rows, "dimension", sources,
                                        source_hashes, evidence)
        write_csv(table_dir / "study_design.csv", projection.rows)
        _write_tex(table_dir / "study_design.tex", study_design_table_tex(projection.rows) + projection.prose,
                   "tab:study-design", "Study dimensions and controlled evaluation settings.", projection.rows,
                   required_prose=projection.prose)
        entry = _design_manifest_entry(
            "study_design", "Study dimensions and controlled evaluation settings.",
            "study_design", len(study_rows), sources,
        )
        entry["publication_projection"] = projection.metadata
        entries.append(entry)
    if len(publication_rows) >= 2:
        projection = _design_projection("method_components", publication_rows, "component", sources,
                                        source_hashes, evidence)
        write_csv(table_dir / "method_components.csv", projection.rows)
        _write_tex(table_dir / "method_components.tex", method_components_table_tex(projection.rows) + projection.prose,
                   "tab:method-components", component_caption, projection.rows,
                   required_prose=projection.prose)
        entry = _design_manifest_entry(
            "method_components", component_caption,
            "method_components", len(component_rows), sources,
        )
        entry["publication_projection"] = projection.metadata
        entries.append(entry)
    return entries


def _design_manifest_entry(
    table_id: str, caption: str, role: str, rows: int, sources: list[str]
) -> dict[str, Any]:
    return {
        "id": table_id,
        "caption": caption,
        "latex_path": f"paper/tables/{table_id}.tex",
        "data_path": f"paper/tables/{table_id}.csv",
        "label": f"tab:{table_id.replace('_', '-')}",
        "rows": rows,
        "scientific_role": role,
        "evidence_status": "design_contract",
        "source_data": sources,
    }


def _write_tex(
    path: Path, generated: str, label: str, caption: str, rows: list[dict[str, Any]],
    *, required_prose: str = "",
) -> None:
    from .paper_table_projection_validation import public_table_compact_row_issues

    text = _read(path, 250000)
    exact_public = not public_table_compact_row_issues(rows, text)
    if not exact_public or (required_prose and required_prose not in text) or not _table_source_matches_registered_rows(
        path, label=label, caption=caption, rows=rows
    ):
        atomic_write_text(path, generated)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _write_executed_tables(
    evidence: PaperEvidence, table_dir: Path
) -> list[dict[str, Any]]:
    if evidence.experiments_pending:
        return []
    entries: list[dict[str, Any]] = []
    specs = [
        ("main_results", "main_comparison.csv", "main_results.tex", "tab:main-results", "result", "main_comparison"),
        ("component_ablation_results", "component_ablation.csv", "component_ablation_results.tex", "tab:component-ablation-results", "ablation", "component_ablation"),
        ("robustness_results", "robustness_sensitivity.csv", "robustness_results.tex", "tab:robustness-results", "robustness", "robustness_sensitivity"),
        ("calibration_results", "calibration_analysis.csv", "calibration_results.tex", "tab:calibration-results", "calibration", "calibration_analysis"),
    ]
    for table_id, csv_name, tex_name, label, role, asset_id in specs:
        rows = _read_csv(evidence.root / "experiments" / "results" / "aggregates" / csv_name)
        from .paper_matrix_result_rows import reported_matrix_rows
        rows = reported_matrix_rows(evidence.root, role) or rows
        if not rows:
            continue
        entries.extend(_write_result_panels(evidence, table_dir, table_id, csv_name, tex_name, label, role, asset_id, rows))
    return entries


def _write_result_panels(evidence: PaperEvidence, table_dir: Path, table_id: str, csv_name: str,
                         tex_name: str, label: str, role: str, asset_id: str,
                         all_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Register each bounded table panel with its own complete CSV and source binding."""
    entries = []
    for start in range(0, len(all_rows), 12):
        rows = all_rows[start:start + 12]
        suffix = '' if start == 0 else f'_panel_{start // 12 + 1}'
        panel_id = table_id + suffix
        panel_csv = Path(csv_name).stem + suffix + '.csv'
        panel_tex = Path(tex_name).stem + suffix + '.tex'
        panel_label = label + suffix.replace('_', '-')
        caption = _result_caption(table_id, rows)
        public_rows = project_result_table_rows(rows)
        atomic_write_json(table_dir.parents[1] / f".merak/paper-table-records/{panel_id}.json",
                          {"schema": 1, "records": rows})
        projection = _result_projection(evidence.root, panel_id, csv_name, public_rows, source_rows=rows)
        write_csv(table_dir / panel_csv.replace("main_comparison", "main_results"), projection.rows)
        _write_tex(table_dir / panel_tex, public_results_table_tex(projection.rows, caption=caption, label=panel_label) + projection.prose,
                   panel_label, caption, projection.rows, required_prose=projection.prose)
        entry = _executed_manifest_entry(
            evidence, panel_id, panel_csv, panel_tex, panel_label, role, asset_id, caption, len(rows)
        )
        entry["public_columns"] = list(public_rows[0])
        entry["publication_projection"] = projection.metadata
        entries.append(entry)
    return entries


def _result_caption(table_id: str, rows: list[dict[str, str]]) -> str:
    if all(row.get('ci_method') == 'reported_sequence' for row in rows):
        return ('Executed comparisons by registered condition and seed. Mean and SD describe paired '
                'independent-sequence differences; n counts sequences within each seed. Intervals are '
                'the reported seed-specific 95% Student-t intervals, not intervals across seeds.')
    if table_id == "main_results" and {"theme", "evidence_count", "case_count"}.issubset(rows[0]):
        return "Primary themes with coded-evidence coverage, negative cases, and source triangulation."
    return {
        "main_results": "Executed primary comparison. Intervals are 95% confidence intervals across recorded runs.",
        "component_ablation_results": "Executed controlled alternative analysis with run-level uncertainty.",
        "robustness_results": "Executed validation, stress, or sensitivity analysis with run-level uncertainty.",
        "calibration_results": "Executed secondary-endpoint or validation-curve analysis with run-level uncertainty.",
    }[table_id]


def _executed_manifest_entry(
    evidence: PaperEvidence, table_id: str, csv_name: str, tex_name: str,
    label: str, role: str, asset_id: str, caption: str, rows: int,
) -> dict[str, Any]:
    asset = next((item for item in evidence.asset_plan.get("assets", [])
                  if isinstance(item, dict) and item.get("id") == asset_id), {})
    data_name = csv_name.replace("main_comparison", "main_results")
    provenance = {
        "existing_results": "existing_runtime_result",
        "secondary_analysis": "public_secondary_source",
    }.get(evidence.evidence_mode, "current_runtime_result")
    return {
        "id": table_id, "caption": caption, "latex_path": f"paper/tables/{tex_name}",
        "data_path": f"paper/tables/{data_name}", "label": label, "rows": rows,
        "scientific_role": role, "evidence_status": "executed", "provenance_kind": provenance,
        "source_data": list(asset.get("source_data") or []),
        "uncertainty_encoding": str(asset.get("uncertainty_encoding") or "95% confidence interval across recorded runs"),
    }


def _synthetic_preview_entries(
    evidence: PaperEvidence, table_dir: Path
) -> list[dict[str, Any]]:
    preview = table_dir / "synthetic_preview_results.tex"
    if not evidence.synthetic_preview or not preview.is_file():
        return []
    from .simulation_table_portfolio import simulation_table_bindings_from_manifest
    from .paper_table_source_labels import selected_table_source_records
    payload = json.loads((evidence.root / "experiments/results/simulated/SIMULATION_MANIFEST.json").read_text(encoding="utf-8-sig"))
    contribution = str((evidence.selected_idea.get("publication") or {}).get("contribution_type") or "")
    bindings = simulation_table_bindings_from_manifest(payload, contribution)
    source_records = selected_table_source_records(_read(preview, 500000))
    entries = []
    for binding in bindings:
        label, role, data_path = binding.label, binding.scientific_role, binding.data_path
        rows = _read_csv(evidence.root / data_path)
        record = source_records.get(label)
        if not rows or record is None:
            raise ValueError(f"Selected simulation table {label} has no current bound source and data")
        table_id = "simulation_" + binding.stable_role
        caption = record["caption"]
        entries.append({
            "id": table_id, "caption": caption,
            "latex_path": "paper/tables/synthetic_preview_results.tex",
            "data_path": data_path, "label": label, "rows": len(rows),
            "scientific_role": role, "evidence_status": "synthetic_preview",
            "provenance_kind": "deterministic_simulation_preview",
            "paper_selected": True, "manuscript_eligible": True, "submission_eligible": False,
            "source_data": [data_path],
            "uncertainty_encoding": "Prespecified 95% interval encoded by registered condition-dependent widths.",
        })
        if binding.stable_role == "main_comparison":
            from .simulation_primary_table import needs_primary_matrix, primary_comparison_panels, panel_binding
            if needs_primary_matrix(rows):
                panels = primary_comparison_panels(rows, label)
                for number, panel in enumerate(panels):
                    if panel.label not in source_records:
                        raise ValueError("Selected primary table is missing a source-bound comparison panel")
                    if number == 0:
                        entry = entries[-1]
                        entry.update({"rows": len(panel.source_row_indices), "primary_panel_binding": panel_binding(panel)})
                    else:
                        entry = {**entries[-1], "id": table_id + f"_panel_{number + 1}", "label": panel.label,
                                 "caption": source_records[panel.label]["caption"], "rows": len(panel.source_row_indices),
                                 "primary_panel_binding": panel_binding(panel)}
                        entries.append(entry)
        if binding.stable_role == "calibration_risk_coverage":
            from .simulation_calibration_table import append_calibration_panel_entries

            append_calibration_panel_entries(entries, rows, label, source_records)
    return entries


def _design_projection(
    table_id: str, rows: list[dict[str, str]], identity_key: str,
    sources: list[str], source_hashes: dict[str, str], evidence: PaperEvidence,
) -> Any:
    from .public_table_prose_projection import project_public_table_prose

    fields = {"component": "publication_name", "function": "publication_description",
              "evaluation": "publication_evaluation"}
    bindings = []
    for index, row in enumerate(rows):
        bindings.append({key: [{
            "source_path": relative, "source_sha256": source_hashes[relative],
            "source_symbol": f"/mechanisms/{index}/{fields[key]}" if key in fields else "",
        } for relative in sources if relative in source_hashes
           and (key not in fields or relative == "ideas/SELECTED_IDEA.json")]
            for key in row})
    from .method_table_presentation import PRESENTATION, presentation_bindings
    current_method = table_id == 'method_components' and PRESENTATION in source_hashes
    if current_method:
        bindings = presentation_bindings(rows, source_hashes)
    return project_public_table_prose(
        table_id, rows, identity_key=identity_key,
        column_labels={"component": "Method element", "function": "Declared design intent" if current_method else "Original planned role",
                       "evaluation": "Evaluation protocol" if current_method else "Initial comparison checklist",
                       "dimension": "Dimension", "setting": "Setting", "purpose": "Scientific purpose"},
        source_bindings=bindings,
    )


def _result_projection(root: Path, table_id: str, csv_name: str, rows: list[dict[str, str]], *, source_rows: list[dict] | None = None) -> Any:
    from .public_table_prose_projection import project_public_table_prose

    relative = "experiments/results/aggregates/" + csv_name
    digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    labels = {"method": "Method", "metric": "Endpoint", "split": "Evaluation condition",
              "estimate": "Mean ± SD", "n": "n", "interval": "95% CI", "theme": "Theme",
              "evidence_count": "Evidence records", "case_count": "Cases",
              "negative_case_count": "Negative cases", "source_count": "Sources", "mean": "Case coverage"}
    bindings = []
    for index, row in enumerate(rows):
        original = source_rows[index] if source_rows else {}
        source = original.get('source_data', relative) if original.get('ci_method') == 'reported_sequence' else relative
        source_index = original.get('source_row_index', index)
        source_hash = hashlib.sha256((root / source).read_bytes()).hexdigest() if source != relative else digest
        bindings.append({key: [{"source_path": source, "source_sha256": source_hash,
                               "source_symbol": f"rows[{source_index}]"}] for key in row})
    return project_public_table_prose(
        table_id, rows, identity_key="theme" if "theme" in rows[0] else "method",
        column_labels=labels, source_bindings=bindings,
        column_kinds={key: "text" if key in {"method", "metric", "split", "theme"} else "number"
                      for key in rows[0]},
    )
