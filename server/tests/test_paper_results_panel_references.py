"""Results reuse panel references only from their own exact reachable table proof."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from server.services.paper_drafting import SECTION_SPECS, PaperDraftingService
from server.services.simulation_table_projection_binding import CANONICAL_TABLE, PUBLICATION_BINDING
from server.services.table_panel_reference_contract import section_primary_panel_parents
from server.tests.test_table_panel_reference_contract import LABEL, _bundle, _files, _json, _sha, _write


RESULT_SPEC = next(spec for spec in SECTION_SPECS if spec.id == "results")
RESULT_PATH = "paper/sections/05_results.tex"


def _section(root: Path, route: str = "derived") -> tuple[Path, str]:
    _bundle(root, route)
    references = "\n".join(r"Table~\ref{" + label + "} reports the matched evidence with uncertainty."
                           for label in (LABEL, "tab:preview-ablation", "tab:preview-robustness-calibration", "tab:preview-calibration"))
    analytical = (
        "The main comparison compares matched baseline conditions, while overlapping confidence intervals "
        "identify pairwise differences that remain uncertain. The component ablation is a matched removal "
        "analysis with each delta interpreted under fixed controls and uncertainty.\n\n"
        "The robustness stress analysis shows degradation and sensitivity across held-out shift. "
        "Calibration is characterized by coverage and selective risk. These controls do not establish "
        "a general superiority claim; the intervals bound the interpretation to the registered comparisons.\n\n"
    )
    padding = (
        "The analysis compares matched conditions, examines interval overlap, and records uncertainty "
        "at the independent run. Each trend is bounded to the registered benchmark, stress range, "
        "and evaluation endpoint. "
    ) * 24
    text = ("\\section{Results}\n\\input{synthetic_preview_figures}\n"
            "\\input{tables/synthetic_preview_results}\n" + references + "\n\n" + analytical + padding + r"\cite{ref1,ref2}")
    _write(root, "paper/synthetic_preview_figures.tex", b"% No additional selected quantitative graphics in this table-only fixture.\n")
    _write(root, "paper/references.bib", b"@article{ref1,title={Registered source one}}\n@article{ref2,title={Registered source two}}\n")
    _write(root, RESULT_PATH, text.encode("utf-8"))
    return root / RESULT_PATH, text


def _review(root: Path) -> dict:
    return PaperDraftingService().section_review(root, RESULT_SPEC,
                                                 {"mode": "synthetic_preview", "submission_eligible": False}, [])


@pytest.mark.parametrize("route", ["original", "derived"])
def test_real_results_review_uses_reachable_exact_panels_and_direct_parent_ref(tmp_path, route):
    path, text = _section(tmp_path, route)
    before = _files(tmp_path)
    assert len(section_primary_panel_parents(tmp_path, path)) == 7
    review = _review(tmp_path)
    assert review["passed"], review
    assert _review(tmp_path)["passed"] and path.read_text(encoding="utf-8") == text
    assert _files(tmp_path) == before
    manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
    assert len([item for item in manifest["tables"] if item.get("primary_panel_binding")]) == 8


@pytest.mark.parametrize("defect", ["no_input", "commented_input", "foreign_input", "parent_missing", "parent_comment", "parent_caption"])
def test_unreachable_tables_or_caption_only_parent_do_not_waive_panel_references(tmp_path, defect):
    path, text = _section(tmp_path)
    if defect in {"no_input", "commented_input", "foreign_input"}:
        replacement = {"no_input": "", "commented_input": "% \\input{tables/synthetic_preview_results}",
                       "foreign_input": "\\input{tables/unregistered_copy}"}[defect]
        text = text.replace(r"\input{tables/synthetic_preview_results}", replacement)
        if defect == "foreign_input":
            _write(tmp_path, "paper/tables/unregistered_copy.tex", (tmp_path / CANONICAL_TABLE).read_bytes())
    else:
        text = text.replace(r"Table~\ref{" + LABEL + "} reports the matched evidence with uncertainty.", "")
        if defect == "parent_comment":
            text += "\n% Table~\\ref{" + LABEL + "} reports the comparison.\n"
        elif defect == "parent_caption":
            text += r"\begin{figure}\caption{Table~\ref{" + LABEL + r"} reports the comparison.}\label{fig:caption-only}\end{figure}"
    path.write_text(text, encoding="utf-8")
    before = _files(tmp_path)
    review = _review(tmp_path)
    assert not review["passed"]
    assert any("omits registered asset references" in issue and LABEL + "-panel-2" in issue for issue in review["issues"])
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["missing_proof", "stale_proof", "row_binding", "source_csv", "foreign_panel", "fake_values"])
def test_results_consumer_requires_current_scientific_proof_not_registration_alone(tmp_path, defect):
    path, text = _section(tmp_path)
    if defect == "missing_proof":
        (tmp_path / PUBLICATION_BINDING).unlink()
    elif defect == "stale_proof":
        proof = json.loads((tmp_path / PUBLICATION_BINDING).read_text())
        proof["simulation_manifest_sha256"] = "0" * 64
        _json(tmp_path, PUBLICATION_BINDING, proof)
    elif defect == "row_binding":
        manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
        panel = next(item for item in manifest["tables"] if item["label"] == LABEL + "-panel-2")
        panel["primary_panel_binding"]["source_row_indices"] = [0]
        _json(tmp_path, "paper/tables/TABLE_MANIFEST.json", manifest)
    elif defect == "source_csv":
        source = tmp_path / "experiments/results/simulated/main_comparison.csv"
        source.write_bytes(source.read_bytes().replace(b"0.005", b"0.006", 1))
    else:
        table = tmp_path / CANONICAL_TABLE
        changed = table.read_text(encoding="utf-8")
        changed = (changed.replace("0.005 [0.001, 0.009]", "0.006 [0.001, 0.009]", 1)
                   if defect == "fake_values" else changed.replace(LABEL + "-panel-2", "tab:foreign-panel-2"))
        table.write_text(changed, encoding="utf-8")
        proof = json.loads((tmp_path / PUBLICATION_BINDING).read_text())
        proof["latex_sha256"] = _sha(table.read_bytes())
        _json(tmp_path, PUBLICATION_BINDING, proof)
        manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
        for item in manifest["tables"]:
            item["latex_sha256"] = proof["latex_sha256"]
            if defect == "foreign_panel" and item["label"] == LABEL + "-panel-2":
                item["label"] = "tab:foreign-panel-2"
        _json(tmp_path, "paper/tables/TABLE_MANIFEST.json", manifest)
    before = _files(tmp_path)
    review = _review(tmp_path)
    assert not review["passed"] and any("panel reference is invalid" in issue for issue in review["issues"])
    assert path.read_text(encoding="utf-8") == text and _files(tmp_path) == before


def test_table_continuation_proof_does_not_remove_independent_scientific_role_reference(tmp_path):
    path, text = _section(tmp_path)
    path.write_text(text.replace(r"Table~\ref{tab:preview-calibration} reports the matched evidence with uncertainty.", ""), encoding="utf-8")
    review = _review(tmp_path)
    assert not review["passed"]
    missing = [issue for issue in review["issues"] if "omits registered asset references" in issue]
    assert missing == ["synthetic results preview omits registered asset references: tab:preview-calibration"]


@pytest.mark.parametrize("defect", ["changed", "missing"])
def test_results_validator_frozen_source_mirror_binds_panel_consumer_implementation(tmp_path, monkeypatch, defect):
    from server.services.paper_stage_validator_signature import stage_validator_signature
    from server.utils.runtime_source_root import server_source_root

    source = server_source_root()
    expected = stage_validator_signature("results")
    mirror = tmp_path / "executable/merak-source/server"
    shutil.copytree(source / "services", mirror / "services", ignore=shutil.ignore_patterns("__pycache__"))
    (mirror / "utils").mkdir()
    shutil.copy2(source / "utils/runtime_source_root.py", mirror / "utils/runtime_source_root.py")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "executable"), raising=False)
    assert stage_validator_signature("results") == expected
    helper = mirror / "services/table_panel_reference_contract.py"
    if defect == "changed":
        helper.write_bytes(helper.read_bytes() + b"\n# Pure fixture consumer implementation change.\n")
        assert stage_validator_signature("results") != expected
    else:
        helper.unlink()
        with pytest.raises((FileNotFoundError, RuntimeError)):
            stage_validator_signature("results")
