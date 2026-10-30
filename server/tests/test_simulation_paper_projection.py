"""Paper portfolio projection is source-owned, hash-bound and evidence preserving."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services import simulation_publication_attestation as attestation
from server.services.figure_artifacts import figure_artifact_registry
from server.services.paper_artifacts import simulation_manifest_semantic_hash
from server.services.simulation_artifact_io import simulation_figures_tex
from server.services.simulation_figure_portfolio import selected_simulation_figures
from server.services.simulation_paper_projection import refresh_simulation_paper_projection
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION, SIMULATION_STABLE_IDS,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _bundle(root: Path, monkeypatch) -> tuple[Path, list[dict]]:
    """Isolate file transactions; scientific fields have separate full-owner coverage."""
    from server.services.simulation_publication_registry import simulation_figure_production_route

    data = root / "experiments/results/simulated/locked.csv"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"unit,metric\nfixture,0.73\n")
    figures, rendered = [], []
    for asset_id in SIMULATION_STABLE_IDS.values():
        source = root / f"figures/simulated/{asset_id}.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"raise RuntimeError('Fixture sources must not execute')\n")
        outputs = {kind: source.with_suffix(f".{kind}") for kind in ("pdf", "svg", "png")}
        for path in outputs.values():
            path.write_bytes(b"hash-bound local output fixture")
        label = "fig:" + asset_id.replace("_", "-")
        figures.append({"id": asset_id, "producer_kind": "deterministic", "label": label,
                        "source": source.relative_to(root).as_posix(), "source_sha256": _hash(source),
                        "outputs": {kind: path.relative_to(root).as_posix() for kind, path in outputs.items()},
                        "output_sha256": {kind: _hash(path) for kind, path in outputs.items()}})
        rendered.append({"id": asset_id, "stem": source.stem, "label": label,
                         "description": "Scientific comparison"})
    paper = root / "paper/synthetic_preview_figures.tex"
    paper.parent.mkdir()
    paper.write_text(simulation_figures_tex(rendered), encoding="utf-8")
    table = root / "paper/tables/synthetic_preview_results.tex"
    table.parent.mkdir()
    table.write_bytes(b"Bound table fixture\n")
    manifest = root / attestation.MANIFEST_RELATIVE
    manifest.write_text(json.dumps({
        "schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
        "evidence_status": "synthetic_preview", "simulation_id": "locked-fixture",
        "data_files": [{"path": data.relative_to(root).as_posix(), "sha256": _hash(data)}],
        "figure_files": figures, "paper_figures": paper.relative_to(root).as_posix(),
        "paper_figures_sha256": _hash(paper), "paper_table": table.relative_to(root).as_posix(),
        "paper_table_sha256": _hash(table),
    }), encoding="utf-8")
    for figure in figures:
        figure_artifact_registry.record(
            output_dir=root / "figures", figure_type="matplotlib", description="Scientific comparison",
            output_path=str(root / figure["outputs"]["pdf"]), source_path=str(root / figure["source"]),
            metadata={**simulation_figure_production_route(figure), "semantic_key": figure["id"],
                      "scientific_role": "result", "evidence_status": "synthetic_preview",
                      "provenance_kind": "deterministic_simulation_preview", "label": figure["label"],
                      "simulation_id": "locked-fixture", "paper_selected": True,
                      "source_data": [data.relative_to(root).as_posix()],
                      "source_data_sha256": {data.relative_to(root).as_posix(): _hash(data)},
                      "simulation_manifest_sha256": _hash(manifest)},
        )
    selected = root / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir()
    selected.write_text(json.dumps({"schema": 2, "publication": {"contribution_type": "system_architecture"}}))
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    planned.parent.mkdir()
    planned.write_text(json.dumps({"schema": 5, "simulation_manifest": attestation.MANIFEST_RELATIVE,
                                  "simulation_manifest_sha256": _hash(manifest),
                                  "figures": figure_artifact_registry.load(root / "figures")["figures"]}))
    monkeypatch.setattr(attestation, "simulation_manifest_contract_issues", lambda _payload: [])
    return manifest, figures


@pytest.mark.parametrize("contribution", [
    "model_architecture", "objective_mechanism", "experimental_protocol", "system_architecture",
    "dataset_benchmark", "empirical_discovery", "theory_proof",
    "clinical_biological_mechanism", "qualitative_framework",
])
def test_paper_projection_uses_the_same_contribution_portfolio(contribution):
    from server.services.evidence_asset_portfolio import selected_evidence_asset_ids

    records = [{"id": asset_id} for asset_id in SIMULATION_STABLE_IDS.values()]
    before = [dict(record) for record in records]
    selected = selected_simulation_figures(records, contribution)
    assert {record["id"] for record in selected} == selected_evidence_asset_ids(contribution)
    assert records == before and len(records) == 7


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unknown"])
def test_invalid_portfolios_fail_without_selecting_a_generic_replacement(defect):
    records = [{"id": asset_id} for asset_id in SIMULATION_STABLE_IDS.values()]
    if defect == "missing":
        records.pop(0)
    elif defect == "duplicate":
        records.append(dict(records[0]))
    with pytest.raises(ValueError):
        selected_simulation_figures(records, "unsupported" if defect == "unknown" else "system_architecture")


def test_cached_projection_preserves_all_evidence_and_scientific_identity(tmp_path, monkeypatch):
    manifest, figures = _bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    payload = json.loads(manifest.read_text())
    assert refresh_simulation_paper_projection(tmp_path)
    after = json.loads(manifest.read_text())
    assert after["figure_files"] == payload["figure_files"] and len(after["figure_files"]) == 7
    assert simulation_manifest_semantic_hash(after) == simulation_manifest_semantic_hash(payload)
    derived = {"synthetic_preview_figures.tex", "SIMULATION_MANIFEST.json", "FIGURE_MANIFEST.json",
               "FIGURE_MANIFEST.md", "PLANNED_RESULT_MANIFEST.json"}
    assert all(path.read_bytes() == content for path, content in before.items() if path.name not in derived)
    selected = {item["id"] for item in selected_simulation_figures(figures, "system_architecture")}
    tex = (tmp_path / after["paper_figures"]).read_text()
    assert all((f"\\label{{{item['label']}}}" in tex) is (item["id"] in selected) for item in figures)
    registered = figure_artifact_registry.load(tmp_path / "figures")["figures"]
    assert {item["id"] for item in registered if item["metadata"]["paper_selected"]} == selected
    assert all(item["metadata"]["simulation_manifest_sha256"] == _hash(manifest) for item in registered)
    planned = json.loads((tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json").read_text())
    assert planned["simulation_manifest_sha256"] == _hash(manifest)
    assert all(item["metadata"]["simulation_manifest_sha256"] == _hash(manifest) for item in planned["figures"])
    current = _files(tmp_path)
    assert not refresh_simulation_paper_projection(tmp_path)
    assert _files(tmp_path) == current


def test_reference_gate_keeps_rejecting_unselected_includes_instead_of_inventing_refs(tmp_path, monkeypatch):
    from server.services.paper_complete_validation import _reference_issues

    _manifest, figures = _bundle(tmp_path, monkeypatch)
    selected = selected_simulation_figures(figures, "system_architecture")
    prose = " ".join(f"Figure~\\ref{{{item['label']}}} reports its bound comparison." for item in selected)
    include = tmp_path / "paper/synthetic_preview_figures.tex"
    issues = []
    _reference_issues({"paper": tmp_path / "paper"}, prose + include.read_text(), issues)
    assert any("scientific assets included but never referenced" in issue for issue in issues)
    assert refresh_simulation_paper_projection(tmp_path)
    issues = []
    _reference_issues({"paper": tmp_path / "paper"}, prose + include.read_text(), issues)
    assert not issues
    assert all(f"\\ref{{{item['label']}}}" not in prose for item in figures if item not in selected)


@pytest.mark.parametrize("defect", ["data", "source", "variant", "include", "table", "schema", "planned", "label"])
def test_cached_projection_refuses_stale_evidence_before_any_write(tmp_path, monkeypatch, defect):
    manifest, figures = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    paths = {"data": payload["data_files"][0]["path"], "source": figures[0]["source"],
             "variant": figures[0]["outputs"]["png"], "include": payload["paper_figures"],
             "table": payload["paper_table"]}
    if defect in paths:
        (tmp_path / paths[defect]).write_bytes(b"changed")
    elif defect == "schema":
        payload["schema"] -= 1
        manifest.write_text(json.dumps(payload))
    elif defect == "planned":
        (tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json").write_text('{"schema": 4}')
    else:
        registry = tmp_path / "figures/FIGURE_MANIFEST.json"
        entries = json.loads(registry.read_text())
        entries["figures"][0]["metadata"]["label"] = "fig:invented"
        registry.write_text(json.dumps(entries))
    before = _files(tmp_path)
    with pytest.raises(ValueError):
        refresh_simulation_paper_projection(tmp_path)
    assert _files(tmp_path) == before


def test_partial_projection_registration_failure_rolls_back_every_owned_file(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch)
    before = _files(tmp_path)
    original = figure_artifact_registry.record
    calls = 0

    def fail_after_first(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("local registration fixture failed")
        return original(**kwargs)

    monkeypatch.setattr(figure_artifact_registry, "record", fail_after_first)
    with pytest.raises(RuntimeError, match="local registration fixture failed"):
        refresh_simulation_paper_projection(tmp_path)
    assert calls == 2 and _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["semantic_key", "managed_by", "foreign_path", "foreign_key"])
def test_conflicting_registry_identity_fails_before_replacement_can_delete_assets(tmp_path, monkeypatch, defect):
    _bundle(tmp_path, monkeypatch)
    path = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = json.loads(path.read_text())
    if defect in {"semantic_key", "managed_by"}:
        payload["figures"][0]["metadata"][defect] = (
            payload["figures"][1]["id"] if defect == "semantic_key" else "user"
        )
    else:
        import copy

        foreign = copy.deepcopy(payload["figures"][0])
        foreign["id"] = "unrelated-asset"
        if defect == "foreign_path":
            foreign["metadata"]["semantic_key"] = foreign["id"]
        else:
            foreign["source_path"] = "figures/diagrams/unrelated.py"
            foreign["output_path"] = "figures/diagrams/unrelated.pdf"
        payload["figures"].append(foreign)
    path.write_text(json.dumps(payload))
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="identity|collides"):
        refresh_simulation_paper_projection(tmp_path)
    assert _files(tmp_path) == before


def test_noop_requires_the_planned_embedded_selection_to_match(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch)
    assert refresh_simulation_paper_projection(tmp_path)
    path = tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    planned = json.loads(path.read_text())
    for figure in planned["figures"]:
        figure["metadata"]["paper_selected"] = True
    path.write_text(json.dumps(planned))
    scientific = {item: content for item, content in _files(tmp_path).items()
                  if item.suffix in {".py", ".csv", ".pdf", ".svg", ".png"}}
    assert refresh_simulation_paper_projection(tmp_path)
    current = json.loads(path.read_text())
    assert sum(figure["metadata"]["paper_selected"] for figure in current["figures"]) == 4
    assert all(item.read_bytes() == content for item, content in scientific.items())
    before = _files(tmp_path)
    assert not refresh_simulation_paper_projection(tmp_path)
    assert _files(tmp_path) == before


def test_noncanonical_nested_output_is_rejected_without_rewriting_paths(tmp_path, monkeypatch):
    manifest, figures = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    target = payload["figure_files"][0]
    updates = {}
    for relative in (target["source"], *target["outputs"].values()):
        old = tmp_path / relative
        new = old.parent / "nested" / old.name
        new.parent.mkdir(exist_ok=True)
        old.rename(new)
        updates[relative] = new.relative_to(tmp_path).as_posix()
    target["source"] = updates[target["source"]]
    target["outputs"] = {kind: updates[value] for kind, value in target["outputs"].items()}
    manifest.write_text(json.dumps(payload))
    for path in (tmp_path / "figures/FIGURE_MANIFEST.json",
                 tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"):
        inventory = json.loads(path.read_text())
        inventory["simulation_manifest_sha256"] = _hash(manifest)
        for figure in inventory["figures"]:
            figure["metadata"]["simulation_manifest_sha256"] = _hash(manifest)
            if figure["id"] == target["id"]:
                figure["source_path"] = target["source"]
                figure["output_path"] = target["outputs"]["pdf"]
        path.write_text(json.dumps(inventory))
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="canonical flat output"):
        refresh_simulation_paper_projection(tmp_path)
    assert _files(tmp_path) == before
