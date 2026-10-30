"""Pure long-cell notes, source-binding, freeze and LaTeX closure regressions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from server.services.latex_bundle import latex_source_bundle
from server.services.paper_layout_attribution import layout_repair_findings
from server.services.paper_artifacts import bind_table_manifest_hashes, build_table_manifest
from server.services.paper_draft_stages import _authoring_tables
from server.services.paper_evidence import _latex
from server.services.paper_scientific_freeze import (
    freeze_scientific_inputs, rebind_layout_only_derived_inputs, validate_scientific_freeze,
)
from server.services.paper_table_projection import method_components_table_tex, write_csv
from server.services.paper_table_projection_validation import table_publication_projection_issues
from server.services.paper_table_projection_validation import public_table_compact_row_issues
from server.services.public_table_prose_projection import project_public_table_prose
from server.utils.atomic_write import atomic_write_json


def _prepared(root: Path) -> tuple[dict, str]:
    text = ("Compare preserved 95% intervals, restricted readout, and matched removals under all declared conditions. " * 3
            + r"Keep 10% gain, sensor_id, {cohort}, $x_1$, A&B, and \input{untrusted} as literal scientific text.")
    selected = root / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir()
    selected.write_text(json.dumps({"mechanisms": [{"publication_evaluation": text,
                                                   "publication_description": "Preserve task-specific information"}]}), encoding="utf-8")
    binding = {"source_path": "ideas/SELECTED_IDEA.json", "source_sha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
               "source_symbol": "/mechanisms/0/publication_evaluation"}
    rows = [{"component": "Restricted readout", "function": "Preserve task-specific information", "evaluation": text},
            {"component": "Context predictor", "function": "Recover declared temporal context", "evaluation": "Compare matched context removals"}]
    projection = project_public_table_prose("method_components", rows, identity_key="component",
                                          column_labels={"component": "Component", "function": "Function", "evaluation": "Evaluation"},
                                          source_bindings=[{"evaluation": [binding], "function": [{**binding, "source_symbol": "/mechanisms/0/publication_description"}]}, {}])
    directory = root / "paper/tables"
    directory.mkdir(parents=True)
    write_csv(directory / "method_components.csv", projection.rows)
    tex = method_components_table_tex(projection.rows) + projection.prose
    (directory / "method_components.tex").write_text(tex, encoding="utf-8")
    item = {"id": "method_components", "scientific_role": "method_components", "label": "tab:method-components",
            "caption": "Method components, scientific functions, and decisive evaluations.", "rows": 2,
            "data_path": "paper/tables/method_components.csv", "latex_path": "paper/tables/method_components.tex",
            "publication_projection": projection.metadata}
    manifest = build_table_manifest(root, [item])
    atomic_write_json(directory / "TABLE_MANIFEST.json", manifest)
    return manifest, text


def test_full_scientific_prose_is_escaped_visible_and_manifest_bound(tmp_path: Path) -> None:
    manifest, text = _prepared(tmp_path)
    item = manifest["tables"][0]
    assert table_publication_projection_issues(tmp_path, item) == []
    latex = (tmp_path / item["latex_path"]).read_text(encoding="utf-8")
    assert _latex(text) in latex
    assert r"\input{untrusted}" not in latex
    assert r"\textbackslash{}input\{untrusted\}" in latex
    assert latex.index(r"\label{note:method_components-note-1}") > latex.rfind(r"\end{table}")


@pytest.mark.parametrize("fault", ["csv-internal", "wrong-row", "wrong-original", "missing-note", "duplicate-note",
                                  "wrong-reference", "removed-prose", "unsafe-prose", "note-inside-float", "changed-source",
                                  "removed-cell-reference", "changed-short-function", "missing-source-pointer"])
def test_lossy_or_stale_projection_cannot_be_accepted_or_rebound(tmp_path: Path, fault: str) -> None:
    manifest, text = _prepared(tmp_path)
    item = manifest["tables"][0]
    projection = item["publication_projection"]
    note = projection["notes"][0]
    tex_path = tmp_path / item["latex_path"]
    tex = tex_path.read_text(encoding="utf-8")
    if fault == "csv-internal":
        write_csv(tmp_path / item["data_path"], [{"id": "M1", "source_path": "internal/mechanism.py"}])
    elif fault == "wrong-row":
        note["row_index"] = 1
    elif fault == "wrong-original":
        note["original_public_text"] = "Shortened summary falsely replacing the scientific scope"
    elif fault == "missing-note":
        projection["notes"] = []
    elif fault == "duplicate-note":
        projection["notes"].append(copy.deepcopy(note))
    elif fault == "wrong-reference":
        projection["compact_rows"][0]["evaluation"] = "Evaluation details (Note 99)"
        write_csv(tmp_path / item["data_path"], projection["compact_rows"])
    elif fault == "changed-source":
        (tmp_path / "ideas/SELECTED_IDEA.json").write_text("{}", encoding="utf-8")
    elif fault == "missing-source-pointer":
        note["source_bindings"][0]["source_symbol"] = ""
        projection["source_bindings"][0]["evaluation"][0]["source_symbol"] = ""
    else:
        if fault == "removed-prose":
            tex = tex.replace(_latex(text), "Shortened prose")
        elif fault == "unsafe-prose":
            tex = tex.replace(_latex(text), text)
        elif fault == "removed-cell-reference":
            tex = tex.replace("Evaluation details (Note 1)", "Undeclared comparison")
        elif fault == "changed-short-function":
            tex = tex.replace("Preserve task-specific information", "Altered scientific function")
        else:
            body, notes = tex.split("\\par\\noindent", 1)
            tex = body.replace(r"\end{table}", "\\par\\noindent" + notes + r"\end{table}")
        tex_path.write_text(tex, encoding="utf-8")
    # Recomputing byte hashes cannot bless a scientifically lossy projection.
    item["data_sha256"] = hashlib.sha256((tmp_path / item["data_path"]).read_bytes()).hexdigest()
    item["latex_sha256"] = hashlib.sha256(tex_path.read_bytes()).hexdigest()
    _, issues, changed = bind_table_manifest_hashes(tmp_path, manifest)
    assert issues
    assert changed is False
    with pytest.raises(ValueError):
        build_table_manifest(tmp_path, [item])


def test_note_wording_cannot_drift_from_a_current_json_pointer(tmp_path: Path) -> None:
    manifest, _ = _prepared(tmp_path)
    item = manifest["tables"][0]
    source = tmp_path / "ideas/SELECTED_IDEA.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["mechanisms"][0]["publication_evaluation"] = "Different declared comparison scope"
    source.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    projection = item["publication_projection"]
    projection["notes"][0]["source_bindings"][0]["source_sha256"] = digest
    projection["source_bindings"][0]["evaluation"][0]["source_sha256"] = digest
    assert any("differs from its source symbol" in issue for issue in table_publication_projection_issues(tmp_path, item))


def test_short_authored_wording_cannot_be_changed_by_consistent_csv_tex_manifest_edits(tmp_path: Path) -> None:
    manifest, _ = _prepared(tmp_path)
    item = manifest["tables"][0]
    projection = item["publication_projection"]
    changed = "Changed task-specific information under a different scientific mechanism"
    previous = projection["original_public_rows"][0]["function"]
    projection["original_public_rows"][0]["function"] = changed
    projection["compact_rows"][0]["function"] = changed
    write_csv(tmp_path / item["data_path"], projection["compact_rows"])
    tex = tmp_path / item["latex_path"]
    tex.write_text(tex.read_text(encoding="utf-8").replace(_latex(previous), _latex(changed)), encoding="utf-8")
    item["data_sha256"] = hashlib.sha256((tmp_path / item["data_path"]).read_bytes()).hexdigest()
    item["latex_sha256"] = hashlib.sha256(tex.read_bytes()).hexdigest()
    _, issues, _ = bind_table_manifest_hashes(tmp_path, manifest)
    assert any("differs from its source symbol" in issue for issue in issues)


def test_authored_public_field_boundary_whitespace_matches_producer_strip(tmp_path: Path) -> None:
    manifest, _ = _prepared(tmp_path)
    item = manifest["tables"][0]
    source = tmp_path / "ideas/SELECTED_IDEA.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["mechanisms"][0]["publication_description"] = "\n  Preserve task-specific information  \n"
    source.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    projection = item["publication_projection"]
    for row in projection["source_bindings"]:
        for values in row.values():
            for binding in values:
                binding["source_sha256"] = digest
    for note in projection["notes"]:
        for binding in note["source_bindings"]:
            binding["source_sha256"] = digest
    assert table_publication_projection_issues(tmp_path, item) == []
    payload["mechanisms"][0]["publication_description"] = "Preserve altered task-specific information"
    source.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for row in projection["source_bindings"]:
        for values in row.values():
            for binding in values:
                binding["source_sha256"] = digest
    for note in projection["notes"]:
        for binding in note["source_bindings"]:
            binding["source_sha256"] = digest
    assert any("differs from its source symbol" in issue for issue in table_publication_projection_issues(tmp_path, item))


def test_derived_short_cell_remains_hash_bound_without_inventing_a_json_pointer(tmp_path: Path) -> None:
    manifest, _ = _prepared(tmp_path)
    item = manifest["tables"][0]
    derived = tmp_path / "experiments/RUN_SPEC.json"
    derived.parent.mkdir()
    derived.write_text(json.dumps({"budgets": {"seeds": [13, 42, 73]}}), encoding="utf-8")
    item["publication_projection"]["source_bindings"][1]["function"] = [{
        "source_path": "experiments/RUN_SPEC.json", "source_sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
        "source_symbol": "",
    }]
    assert table_publication_projection_issues(tmp_path, item) == []


def test_authoring_inventory_exposes_public_notes_without_internal_bindings(tmp_path: Path) -> None:
    manifest, text = _prepared(tmp_path)
    table = _authoring_tables(manifest)[0]
    assert table["public_notes"][0]["text"] == text
    assert table["public_notes"][0]["row_label"] == "Restricted readout"
    assert "source_symbol" not in json.dumps(table)
    assert "source_sha256" not in json.dumps(table)


def test_short_public_cells_cannot_execute_tex_commands_or_lose_literal_notation() -> None:
    public = r"Preserve {cohort}, $x_1$, 10%, A&B and \input{untrusted} literally"
    rows = [{"component": "Restricted readout", "function": public, "evaluation": "Matched intervention"},
            {"component": "Context predictor", "function": "Conditional representation", "evaluation": "Matched removal"}]
    latex = method_components_table_tex(rows)
    assert public_table_compact_row_issues(rows, latex) == []
    assert _latex(public) in latex
    assert r"\input{untrusted}" not in latex


def test_notes_participate_in_semantic_freeze_and_reachable_pdf_source_bundle(tmp_path: Path) -> None:
    manifest, text = _prepared(tmp_path)
    paper = tmp_path / "paper"
    (paper / "main.tex").write_text(r"\documentclass{article}\begin{document}\input{tables/method_components}\end{document}", encoding="utf-8")
    freeze_scientific_inputs(tmp_path)
    before, paths = latex_source_bundle(paper)
    assert paper / "tables/method_components.tex" in paths
    tex = paper / "tables/method_components.tex"
    tex.write_text(tex.read_text(encoding="utf-8").replace(_latex(text), "Deleted scientific note"), encoding="utf-8")
    after, _ = latex_source_bundle(paper)
    assert before != after
    rebound = rebind_layout_only_derived_inputs(tmp_path, before_manifest=manifest,
                                               target_files=["paper/tables/method_components.tex"])
    assert rebound["passed"] is False
    manifest["tables"][0]["publication_projection"]["notes"][0]["original_public_text"] = "Semantic change"
    atomic_write_json(paper / "tables/TABLE_MANIFEST.json", manifest)
    assert validate_scientific_freeze(tmp_path)["passed"] is False


def test_notes_on_a_following_page_route_layout_repair_to_their_table_source(tmp_path: Path) -> None:
    _prepared(tmp_path)
    (tmp_path / "paper/main.aux").write_text(r"\newlabel{note:method_components-note-1}{{}{4}}", encoding="utf-8")
    findings = layout_repair_findings(tmp_path, ["page 4: overlapping text-block"], ".merak/quality/paper-layout.json")
    assert len(findings) == 1
    assert findings[0]["owner_node"] == "paper"
    assert findings[0]["asset_ids"] == ["method_components"]
    assert findings[0]["target_files"] == ["paper/tables/method_components.tex"]
