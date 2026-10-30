"""A table continuation shares interpretation only through exact producer evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from server.services.paper_artifacts import build_table_manifest
from server.services.paper_evidence import PaperEvidence
from server.services.paper_submission_tables import _synthetic_preview_entries
from server.services.paper_table_source_labels import selected_table_source_records
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION, SIMULATION_STABLE_IDS
from server.services.simulation_primary_table import render_primary_comparison_panels
from server.services.simulation_table_projection_binding import CANONICAL_TABLE, PUBLICATION_BINDING, SIMULATION_MANIFEST, table_projection_record
from server.services.simulation_table_publication import _public_table_text, _renderer_digest
from server.services.table_panel_reference_contract import source_bound_primary_panel_parents
from server.workflows import paper_acceptance_checks_3 as checks
from server.workflows.paper_acceptance_context import PaperGateContext


LABEL = "tab:preview-main-results"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _json(root: Path, relative: str, value: dict) -> None:
    _write(root, relative, json.dumps(value).encode("utf-8"))


def _rows() -> list[dict[str, str]]:
    return [{"dataset": f"Declared dataset {dataset}", "method": f"Named matched condition {method}",
             "value": f"0.{dataset}{method}5", "ci_low": f"0.{dataset}{method}1", "ci_high": f"0.{dataset}{method}9"}
            for method in range(8) for dataset in range(8)]


def _other_tables() -> str:
    return "\n\n".join([
        r"\begin{table*}\caption{Matched ablation}\label{tab:preview-ablation}\midrule" + "\n"
        + r"Named intact condition & +0.000 \\" + "\n" + r"Without named mechanism & -0.012 \\" + "\n"
        + r"\bottomrule\end{table*}",
        r"\begin{table*}\caption{Stress response over Missing channel rate}\label{tab:preview-robustness-calibration}\midrule 0.1 & 0.6\\ 0.2 & 0.5\\\bottomrule\end{table*}",
        r"\begin{table*}\caption{Calibration}\label{tab:preview-calibration}\midrule Named A & 0.11\\ Named B & 0.14\\\bottomrule\end{table*}",
    ])


def _bundle(root: Path, route: str) -> str:
    roles = dict(zip(SIMULATION_STABLE_IDS, ("main_comparison.csv", "ablation.csv", "training_dynamics.csv",
                                          "robustness.csv", "error_analysis.csv", "calibration.csv", "efficiency.csv")))
    data = []
    for role, filename in roles.items():
        path = root / "experiments/results/simulated" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = _rows() if role == "main_comparison" else (
            [{"component_setting": "Named intact condition", "changed_factor": "none", "delta": "+0.000"},
             {"component_setting": "Without named mechanism", "changed_factor": "registered_factor", "delta": "-0.012"}]
            if role == "component_ablation" else [{"method": "Named A", "score": "0.73"}, {"method": "Named B", "score": "0.68"}]
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        data.append({"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())})
    primary = render_primary_comparison_panels(_rows(), "Macro-F1 (higher is better)", "Matched primary comparison", LABEL)
    legacy_body = "\n".join(" & ".join((row["dataset"], row["method"], f"{row['value']} [{row['ci_low']}, {row['ci_high']}]")) + r" \\" for row in _rows())
    legacy = r"\begin{table*}\caption{Matched primary comparison}\label{" + LABEL + r"}\midrule" + "\n" + legacy_body + r"\bottomrule\end{table*}"
    original = (primary if route == "original" else legacy) + "\n\n" + _other_tables()
    _write(root, CANONICAL_TABLE, original.encode("utf-8"))
    payload = {"schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
               "primary_metric": "macro_f1", "metric_direction": "maximize", "paper_table": CANONICAL_TABLE,
               "paper_table_sha256": _sha(original.encode("utf-8")), "data_files": data, "figure_files": [],
               "domain_asset_profile": [{"stable_role": role, "semantic_id": SIMULATION_STABLE_IDS[role],
                                         "data_file": filename, "axis_field": "component_setting" if role == "component_ablation" else "missing_channel_rate"}
                                        for role, filename in roles.items()]}
    _json(root, SIMULATION_MANIFEST, payload)
    _json(root, "ideas/SELECTED_IDEA.json", {"publication": {"contribution_type": "objective_mechanism"}})
    if route == "derived":
        text = _public_table_text(root, payload, "objective_mechanism", original).encode("utf-8")
        proof = table_projection_record(root, payload, text, original.encode("utf-8"), "objective_mechanism", _renderer_digest())
        _write(root, CANONICAL_TABLE, text)
        _json(root, PUBLICATION_BINDING, proof)
    evidence = PaperEvidence(root, "Study", "", "", "", "", "", "",
                             asset_plan={"evidence_mode": "synthetic_preview"},
                             selected_idea={"publication": {"contribution_type": "objective_mechanism"}})
    manifest = build_table_manifest(root, _synthetic_preview_entries(evidence, root / "paper/tables"))
    _json(root, "paper/tables/TABLE_MANIFEST.json", manifest)
    return (root / CANONICAL_TABLE).read_text(encoding="utf-8")


def _context(root: Path, text: str, prose: str | None = None) -> PaperGateContext:
    if prose is None:
        labels = [LABEL, "tab:preview-ablation", "tab:preview-robustness-calibration", "tab:preview-calibration"]
        prose = "\n\n".join("Table~\\ref{" + label + "} reports the matched comparison and uncertainty." for label in labels)
    context = PaperGateContext(None, str(root), False, False, False, {}, root=root, problems=[],
                              expanded_main=prose + "\n\n" + text,
                              table_blocks=re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", text, re.DOTALL),
                              figure_blocks=[])
    for step in (checks.remove_float_blocks, checks.compile_reference_pattern, checks.find_reference_commands,
                 checks.collect_referenced_labels, checks.count_references, checks.compile_discussion_terms,
                 checks.initialize_declared_labels, checks.collect_declared_labels):
        step(context)
    return context


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("route", ["original", "derived"])
def test_complete_current_producer_panels_share_real_parent_prose_without_inventing_refs(tmp_path, route):
    text = _bundle(tmp_path, route)
    context = _context(tmp_path, text)
    before = _files(tmp_path)
    expected = {f"{LABEL}-panel-{number}": LABEL for number in range(2, 9)}
    assert source_bound_primary_panel_parents(tmp_path, context.table_blocks) == expected
    checks.validate_asset_discussion(context)
    assert context.problems == [] and context.ref_count == 4
    checks.validate_asset_discussion(context)
    assert context.problems == [] and _files(tmp_path) == before


@pytest.mark.parametrize("prose", ["", "See Table~\\ref{" + LABEL + "}.", "Table~\\ref{tab:foreign} reports the effect."])
def test_caption_navigation_cannot_replace_a_real_interpreted_parent_reference(tmp_path, prose):
    text = _bundle(tmp_path, "derived")
    context = _context(tmp_path, text, prose)
    checks.validate_asset_discussion(context)
    assert any("not interpreted in prose" in issue or "never referenced in prose" in issue for issue in context.problems)
    assert any(f"{LABEL}-panel-2" in issue for issue in context.problems)


@pytest.mark.parametrize("defect", ["missing_proof", "wrong_parent_id", "wrong_label", "wrong_row_binding", "data_hash", "foreign_path", "unselected", "missing_panel", "foreign_panel", "numeric_rebind", "old_font"])
def test_unbound_missing_foreign_or_resigned_changed_panels_remain_blocking_and_readonly(tmp_path, defect):
    text = _bundle(tmp_path, "derived")
    manifest_path = tmp_path / "paper/tables/TABLE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    panel = next(item for item in manifest["tables"] if item["id"] == "simulation_main_comparison_panel_2")
    if defect == "missing_proof":
        (tmp_path / PUBLICATION_BINDING).unlink()
    elif defect in {"numeric_rebind", "old_font"}:
        text = text.replace("0.005 [0.001, 0.009]", "0.006 [0.001, 0.009]", 1) if defect == "numeric_rebind" else text.replace(r"\small", r"\tiny", 1)
        _write(tmp_path, CANONICAL_TABLE, text.encode("utf-8"))
        proof = json.loads((tmp_path / PUBLICATION_BINDING).read_text())
        proof["latex_sha256"] = _sha(text.encode("utf-8"))
        _json(tmp_path, PUBLICATION_BINDING, proof)
        for item in manifest["tables"]:
            item["latex_sha256"] = proof["latex_sha256"]
    elif defect == "missing_panel":
        text = text.replace(selected_table_source_records(text)[panel["label"]]["source"], "")
    elif defect == "foreign_panel":
        text += r"\begin{table}\caption{Unbound extra comparison}\label{" + LABEL + r"-panel-99}\midrule A & 0.8\\ B & 0.7\\\bottomrule\end{table}"
    else:
        field, value = {"wrong_parent_id": ("id", "simulation_other_primary_panel_2"),
                        "wrong_label": ("label", "tab:foreign-panel-2"),
                        "wrong_row_binding": ("primary_panel_binding", {**panel["primary_panel_binding"], "source_row_indices": [0]}),
                        "data_hash": ("data_sha256", "0" * 64), "foreign_path": ("latex_path", "../foreign.tex"),
                        "unselected": ("paper_selected", False)}[defect]
        panel[field] = value
    _json(tmp_path, "paper/tables/TABLE_MANIFEST.json", manifest)
    context = _context(tmp_path, text)
    before = _files(tmp_path)
    checks.validate_asset_discussion(context)
    assert context.problems and _files(tmp_path) == before
    if defect != "foreign_panel":
        assert any("never referenced in prose" in issue and "-panel-" in issue for issue in context.problems)
    else:
        assert any("never referenced in prose" in issue and "-panel-99" in issue for issue in context.problems)


def test_arbitrary_named_panel_without_any_producer_binding_stays_unreferenced(tmp_path):
    text = r"\begin{table}\caption{Primary}\label{tab:primary}\end{table}" + r"\begin{table}\caption{Continuation}\label{tab:primary-panel-2}\end{table}"
    context = _context(tmp_path, text, r"Table~\ref{tab:primary} reports a comparison.")
    checks.validate_asset_discussion(context)
    assert context.problems == ["scientific asset is included but never referenced in prose: tab:primary-panel-2"]


@pytest.mark.parametrize("defect", ["numeric_rebind", "old_font", "source_csv", "invalid_identity"])
def test_original_table_hash_alone_cannot_attest_changed_panels_or_source_rows(tmp_path, defect):
    text = _bundle(tmp_path, "original")
    table_manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
    if defect in {"numeric_rebind", "old_font"}:
        text = text.replace("0.005 [0.001, 0.009]", "0.006 [0.001, 0.009]", 1) if defect == "numeric_rebind" else text.replace(r"\small", r"\tiny", 1)
        _write(tmp_path, CANONICAL_TABLE, text.encode("utf-8"))
        payload = json.loads((tmp_path / SIMULATION_MANIFEST).read_text())
        payload["paper_table_sha256"] = _sha(text.encode("utf-8"))
        _json(tmp_path, SIMULATION_MANIFEST, payload)
        for item in table_manifest["tables"]:
            item["latex_sha256"] = payload["paper_table_sha256"]
    elif defect == "source_csv":
        path = tmp_path / "experiments/results/simulated/main_comparison.csv"
        path.write_bytes(path.read_bytes().replace(b"0.005", b"0.006", 1))
    else:
        next(item for item in table_manifest["tables"] if item["id"] == "simulation_main_comparison_panel_2")["label"] = []
    _json(tmp_path, "paper/tables/TABLE_MANIFEST.json", table_manifest)
    before = _files(tmp_path)
    context = _context(tmp_path, text)
    checks.validate_asset_discussion(context)
    assert context.problems and _files(tmp_path) == before


def test_derived_projection_cannot_borrow_a_different_current_contribution(tmp_path):
    text = _bundle(tmp_path, "derived")
    _json(tmp_path, "ideas/SELECTED_IDEA.json", {"publication": {"contribution_type": "system_architecture"}})
    context = _context(tmp_path, text)
    checks.validate_asset_discussion(context)
    assert any("different selected contribution" in issue for issue in context.problems)
