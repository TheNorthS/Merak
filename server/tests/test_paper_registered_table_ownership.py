"""A section cannot reconstruct a producer-owned table or crash complete validation."""

import json
from types import SimpleNamespace

from server.services.paper_table_ownership import registered_table_copy_issues
from server.services.paper_consistency_findings import complete_consistency_findings
from server.services.paper_prose_references import checked_asset_prose_references


TABLE = r"\begin{table}\caption{Method components}\label{tab:components}Registered cells.\end{table}"


def _registered(root):
    directory = root / "paper/tables"
    directory.mkdir(parents=True)
    (directory / "components.tex").write_text(TABLE)
    (directory / "TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": [
        {"label": "tab:components", "latex_path": "paper/tables/components.tex"}]}))
    return directory / "components.tex"


def test_copy_is_rejected_but_prose_reference_and_canonical_input_are_allowed(tmp_path):
    source = _registered(tmp_path)
    original = source.read_bytes()
    assert registered_table_copy_issues(tmp_path, TABLE)
    assert not registered_table_copy_issues(tmp_path, r"Table~\ref{tab:components}.\input{tables/components}")
    assert source.read_bytes() == original


def test_duplicate_table_copy_routes_to_its_section_without_touching_registered_source(tmp_path):
    source = _registered(tmp_path)
    paths = {"root": tmp_path, "paper": tmp_path / "paper"}
    findings = complete_consistency_findings(paths, [SimpleNamespace(id="method", filename="03_method.tex")],
        {"method": TABLE}, {"tab:components"}, {"tab:components"}, set(), {})
    assert len(findings) == 1
    assert findings[0]["stage_id"] == "method"
    assert findings[0]["target_files"] == ["paper/sections/03_method.tex"]
    assert source.read_text() == TABLE


def test_invalid_panel_binding_remains_a_failed_gate_instead_of_crashing(tmp_path, monkeypatch):
    import server.services.table_panel_reference_contract as panels
    def invalid(*_):
        raise ValueError("Registered table source needs one unique public label per table")
    monkeypatch.setattr(panels, "source_bound_primary_panel_parents", invalid)
    issues = []
    refs = checked_asset_prose_references(tmp_path, TABLE * 2 + r"Table~\ref{tab:components}", issues)
    assert refs == {"tab:components"}
    assert len(issues) == 1 and "unique public label" in issues[0]
