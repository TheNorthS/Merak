"""Finite current-schema slide assets; no simulation, model or scientific execution.

All values are explicit local test constants. Files and hashes are real; this
fixture contains no workflow acceptance record and proves only asset binding.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.services.publication_figure_labels import concept_labels
from server.services.figure_routing import recommend_figure_route
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION, SIMULATION_STABLE_IDS,
    SIMULATION_STABLE_ROLES, SIMULATION_PLOT_FAMILIES, simulation_manifest_contract_issues,
)


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base(root: Path) -> None:
    _json(root / "ideas/SELECTED_IDEA.json", {
        "schema": 2, "title": "Bound Benchmark Study", "problem_statement": "The registered setting requires a robust comparison.",
        "hypothesis": "The declared condition may change the endpoint.",
        "claims": [{"id": "C1", "statement": "The proposed condition changes the declared endpoint.",
                    "publication_statement": "The proposed condition changes the declared endpoint."}],
        "mechanisms": [{"id": "M1", "name": "Controlled representation", "description": "Isolates the declared mechanism.",
                        "publication_name": "Controlled representation", "publication_description": "Isolates the declared mechanism.",
                        "publication_evaluation": "Compare matched conditions.", "required": True}],
        "publication": {"language": "en", "method_name": "Declared condition", "contribution_type": "objective_mechanism",
                        "comparator_names": ["Reference condition", "Declared condition"]},
        "falsification_conditions": ["The matched control reaches the same declared endpoint."],
    })
    _json(root / "experiments/METHOD_CONTRACT.json", {"schema": 2, "evaluation_contract": {
        "comparators_or_controls": ["Reference condition", "Matched control"], "component_tests": ["Remove controlled representation"],
    }})
    _json(root / "figures/SCIENTIFIC_ASSET_PLAN.json", {"evidence_mode": "synthetic_preview", "submission_eligible": False})
    results = root / "experiments/results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "analysis.md").write_text("# Registered local fixture\nFindings are bounded to the registered benchmark and declared controls.\n", encoding="utf-8")
    paper = root / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(r"\documentclass{article}\begin{document}Local binding fixture\end{document}", encoding="utf-8")
    tables = paper / "tables"
    tables.mkdir()
    (tables / "synthetic_preview_results.tex").write_text(
        r"\begin{table}\caption{Finite local binding fixture}\label{tab:local-fixture}"
        r"\begin{tabular}{lc}\toprule Condition & Score\\\midrule"
        r"Reference condition & 0.60\\Declared condition & 0.70\\\bottomrule\end{tabular}\end{table}", encoding="utf-8")


def _figure(root: Path, role: str, identity: str, index: int) -> tuple[dict, Path, Path]:
    import fitz
    from PIL import Image, ImageDraw

    stem = identity.removeprefix("synthetic_preview_")
    data = root / f"experiments/results/simulated/{stem}.csv"
    source = root / f"figures/simulated/simulated_{stem}.py"
    data.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)
    direction = "minimize" if role in {"error_analysis", "calibration_risk_coverage"} else "maximize"
    data.write_text("method,value,ci_low,ci_high,metric_direction\n"
                    f"Reference condition,0.60,0.58,0.62,{direction}\n"
                    f"Declared condition,0.70,0.68,0.72,{direction}\n", encoding="utf-8")
    source.write_text("# Static source identity fixture; deliberately not executed.\nLOCAL_VALUES = (0.60, 0.70)\n", encoding="utf-8")
    pdf, svg, png = (source.with_suffix("." + suffix) for suffix in ("pdf", "svg", "png"))
    document = fitz.open()
    page = document.new_page(width=600, height=360)
    page.insert_text((36, 44), f"Local asset binding fixture {index}", fontsize=14)
    for position, value in enumerate((0.60, 0.70)):
        page.draw_rect(fitz.Rect(90 + position * 170, 280 - value * 200, 180 + position * 170, 280), color=(0.1, 0.5, 0.6), fill=(0.1, 0.5, 0.6))
    document.save(pdf)
    document.close()
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="360"><rect x="90" y="160" width="90" height="120" fill="#198099"/><rect x="260" y="140" width="90" height="140" fill="#198099"/></svg>', encoding="utf-8")
    image = Image.new("RGB", (1200, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 320, 360, 560), fill="#198099")
    draw.rectangle((520, 280, 700, 560), fill="#198099")
    image.save(png)
    record = {"id": identity, "producer_kind": "deterministic", "publication_labels": concept_labels(["Declared endpoint"], namespace=identity),
              "plot_family": SIMULATION_PLOT_FAMILIES[role], "metric_direction": direction,
              "source": source.relative_to(root).as_posix(), "source_sha256": _sha(source),
              "outputs": {kind: path.relative_to(root).as_posix() for kind, path in (("pdf", pdf), ("svg", svg), ("png", png))},
              "output_sha256": {kind: _sha(path) for kind, path in (("pdf", pdf), ("svg", svg), ("png", png))}}
    record.update(recommend_figure_route({"id": identity, "kind": "figure", "figure_nature": "quantitative"}))
    return record, data, pdf


def _evidence(root: Path) -> tuple[dict, list[Path]]:
    names = {
        "run_level_results": "run_level_results.csv", "paired_comparisons": "paired_comparisons.csv",
        "run_ledger": "run_ledger.csv", "latency_samples": "latency_samples.csv",
        "registered_axis_results": "registered_axis_results.csv", "provenance_join_audit": "provenance_join_audit.csv",
        "runtime_artifacts": "runtime_artifacts.json", "data_manifest": "data_manifest.csv",
        "raw_checkpoints": "raw_checkpoints.jsonl", "raw_predictions": "raw_predictions.jsonl",
        "raw_measurements": "raw_measurements.jsonl", "generator_source": "reproducibility/generator_source.py",
        "scenario_parameters": "reproducibility/scenario_parameters.json", "reconstruction_tool": "reproducibility/verify_bundle.py",
        "scenario_config": "reproducibility/scenario_config.json", "run_spec": "reproducibility/run_spec.json",
        "method_contract": "reproducibility/method_contract.json",
    }
    package, paths = {}, []
    for key, name in names.items():
        path = root / "experiments/results/simulated" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"fixture_only": True}) + "\n" if path.suffix in {".json", ".jsonl"} else (
            "# Static reconstruction/source identity fixture; never executed.\n" if path.suffix == ".py" else "fixture_id,value\nfinite-local-fixture,0.70\n")
        if key == "provenance_join_audit":
            content = "run_id,join_complete\nlocal-fixture-reference,true\nlocal-fixture-condition,true\n"
        elif key == "run_level_results":
            content = "run_id,model_id,seed,value\nlocal-fixture-reference,local-reference,1729,0.60\nlocal-fixture-condition,local-condition,1729,0.70\n"
        elif key == "run_ledger":
            content = "run_id,model_id,seed\nlocal-fixture-reference,local-reference,1729\nlocal-fixture-condition,local-condition,1729\n"
        elif key == "paired_comparisons":
            content = "reference_model_id,candidate_model_id,axis_id,oriented_mean_effect,in_holm_family\nlocal-reference,local-condition,declared-score,0.10,true\n"
        elif key == "registered_axis_results":
            content = "model_id,axis_id,value\nlocal-reference,declared-score,0.60\nlocal-condition,declared-score,0.70\n"
        path.write_text(content, encoding="utf-8")
        package[key] = path.relative_to(root).as_posix()
        paths.append(path)
    for key in ("generator_source", "scenario_parameters", "scenario_config", "run_spec", "method_contract", "reconstruction_tool"):
        package[key + "_sha256"] = _sha(root / package[key])
    package.update(reconstruction_contract="Finite local binding fixture; no scientific execution.",
                   reconstruction_command="python experiments/results/simulated/reproducibility/verify_bundle.py",
                   provenance_join_contract={"complete": True, "coverage": 1.0})
    return package, paths


def write_current_slide_bundle(root: Path) -> dict[str, Path]:
    """Create current finite files directly, without invoking a generator or renderer."""
    _base(root)
    records, data_paths, outputs = [], [], {}
    for index, (role, identity) in enumerate(SIMULATION_STABLE_IDS.items(), start=1):
        record, data, output = _figure(root, role, identity, index)
        records.append(record)
        data_paths.append(data)
        outputs[identity] = output
    package, evidence_paths = _evidence(root)
    profiles = [{"stable_role": role, "domain_role": role, "semantic_id": identity,
                 "data_file": identity.removeprefix("synthetic_preview_") + ".csv", "analysis_subtype": role,
                 "plot_family": SIMULATION_PLOT_FAMILIES[role], "axis_field": "method", "label": "fig:" + identity,
                 "metric_direction": "minimize" if role in {"error_analysis", "calibration_risk_coverage"} else "maximize"}
                for role, identity in SIMULATION_STABLE_IDS.items()]
    relatives = [path.relative_to(root).as_posix() for path in data_paths]
    payload = {"schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
        "simulation_id": "slides-finite-local-fixture", "simulation_seed": "1729", "primary_metric": "score", "metric_direction": "maximize",
        "asset_domain": "algorithmic", "claim_ids": ["C1"], "fixture_only": True,
        "claim_evidence_map": {"C1": {"figure_ids": list(outputs), "data_files": relatives, "table": "paper/tables/synthetic_preview_results.tex"}},
        "explicit_user_mode": "synthetic_preview", "evidence_status": "synthetic_preview", "manuscript_eligible": True, "submission_eligible": False,
        "completeness_pack": list(SIMULATION_STABLE_ROLES), "domain_asset_profile": profiles, "figure_files": records,
        "data_files": [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path)} for path in [*data_paths, *evidence_paths]],
        "evidence_package": package, "registered_model_suite": [{"method": "Reference condition", "model_id": "local-reference"},
                                                                  {"method": "Declared condition", "model_id": "local-condition"}],
        "registered_ranking_axes": [{"axis_id": "declared-score", "direction": "maximize", "mpid": 0.01, "family_role": "target"}],
        "registered_pair_contract": {"expected_comparison_count": 1, "observed_comparison_count": 1, "complete": True,
            "pairing": "all_unordered_pairs", "holm_family_scope": "unordered_model_pairs_by_non_iid_target_axis",
            "test_method": "paired_student_t_two_sided", "holm_family_size": 1, "reference_row_count": 0}}
    payload.update(paper_table="paper/tables/synthetic_preview_results.tex",
                   paper_table_sha256=_sha(root / "paper/tables/synthetic_preview_results.tex"))
    assert simulation_manifest_contract_issues(payload) == []
    manifest = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    _json(manifest, payload)
    entries = [_registry_entry(root, record, data, manifest) for record, data in zip(records, data_paths, strict=True)]
    _json(root / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": entries})
    (root / "paper/synthetic_preview_figures.tex").write_text("\n".join(
        "\\begin{figure}\\includegraphics{../" + record["outputs"]["pdf"] + "}"
        + "\\caption{Finite local scientific asset fixture}\\label{fig:" + record["id"] + "}\\end{figure}"
        for record in records
    ), encoding="utf-8")
    return {"simulation_manifest": manifest, **outputs}


def _registry_entry(root: Path, record: dict, data: Path, manifest: Path) -> dict:
    relative_data = data.relative_to(root).as_posix()
    return {"id": record["id"], "paper_ready": True, "output_path": record["outputs"]["pdf"],
            "output_sha256": record["output_sha256"]["pdf"], "source_path": record["source"], "source_sha256": record["source_sha256"],
            "metadata": {"semantic_key": record["id"], "managed_by": "merak", "scientific_role": record["id"].removeprefix("synthetic_preview_"),
                **recommend_figure_route({"id": record["id"], "kind": "figure", "figure_nature": "quantitative"}),
                "scientific_question": "What does the finite local binding fixture establish?", "evidence_status": "synthetic_preview",
                "paper_selected": True, "manuscript_eligible": True, "submission_eligible": False,
                "producer_kind": "deterministic", "publication_labels": record["publication_labels"],
                "provenance_kind": "deterministic_simulation_preview", "explicit_user_mode": "synthetic_preview",
                "simulation_manifest": manifest.relative_to(root).as_posix(), "simulation_manifest_sha256": _sha(manifest),
                "simulation_id": "slides-finite-local-fixture", "simulation_seed": "1729",
                "source_data": [relative_data], "source_data_sha256": {relative_data: _sha(data)},
                "rendered_variants": record["outputs"], "rendered_variant_sha256": record["output_sha256"], "fixture_only": True}}


def write_current_publication_table_bundle(root: Path) -> dict[str, Path]:
    """Add actual selected public table projections to the finite seven-role package."""
    from server.services.simulation_table_portfolio import simulation_table_bindings_from_manifest

    outputs = write_current_slide_bundle(root)
    manifest_path = outputs["simulation_manifest"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    blocks = []
    for binding in simulation_table_bindings_from_manifest(payload, "objective_mechanism"):
        if binding.stable_role == "component_ablation":
            body = "Declared condition & 0.70\\\\\nWithout Controlled representation & 0.60\\\\\n"
            relative = binding.data_path
            (root / relative).write_text(
                "method,component_setting,changed_factor,value,ci_low,ci_high,metric_direction\n"
                "Declared condition,Declared condition,none,0.70,0.68,0.72,maximize\n"
                "Declared condition,Without Controlled representation,remove representation,0.60,0.58,0.62,maximize\n", encoding="utf-8")
            profile = next(item for item in payload["domain_asset_profile"] if item["stable_role"] == binding.stable_role)
            profile["axis_field"] = "component_setting"
        else:
            body = "Reference condition & 0.60\\\\\nDeclared condition & 0.70\\\\\n"
        blocks.append(r"\begin{table}\caption{" + binding.scientific_role.capitalize()
                      + r" finite comparison}\label{" + binding.label + r"}\begin{tabular}{lc}\toprule"
                      + r"Condition & Score\\\midrule" + "\n" + body + r"\bottomrule\end{tabular}\end{table}")
    table = root / payload["paper_table"]
    table.write_text("\n".join(blocks), encoding="utf-8")
    payload["paper_table_sha256"] = _sha(table)
    for item in payload["data_files"]:
        item["sha256"] = _sha(root / item["path"])
    assert simulation_manifest_contract_issues(payload) == []
    _json(manifest_path, payload)
    registry_path = root / "figures/FIGURE_MANIFEST.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for entry in registry["figures"]:
        metadata = entry["metadata"]
        metadata["simulation_manifest_sha256"] = _sha(manifest_path)
        metadata["source_data_sha256"] = {relative: _sha(root / relative) for relative in metadata["source_data"]}
    _json(registry_path, registry)
    return outputs
