"""Paper layout checks cannot silently re-sign frozen simulation evidence."""

import hashlib
import json

from server.services.paper_scientific_freeze import refresh_simulation_table_binding


def _fixture(tmp_path):
    table = tmp_path / "paper/tables/synthetic_preview_results.tex"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"original scientific table")
    simulation = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    simulation.parent.mkdir(parents=True)
    simulation.write_text(json.dumps({"paper_table": table.relative_to(tmp_path).as_posix(),
        "paper_table_sha256": hashlib.sha256(table.read_bytes()).hexdigest()}), encoding="utf-8")
    return table, simulation


def test_unchanged_table_binding_is_read_only(tmp_path):
    _table, simulation = _fixture(tmp_path)
    before = simulation.read_bytes()
    assert refresh_simulation_table_binding(tmp_path) == []
    assert simulation.read_bytes() == before


def test_arbitrary_table_edit_cannot_be_hidden_by_resigning_simulation_manifest(tmp_path):
    table, simulation = _fixture(tmp_path)
    before = simulation.read_bytes()
    table.write_bytes(b"unauthorized different numeric scientific values")
    assert refresh_simulation_table_binding(tmp_path)
    assert simulation.read_bytes() == before
