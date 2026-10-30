"""Current hashed bundles repair producer metadata without executing plot/data code."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from server.services import simulation_publication_attestation as attestation
from server.services.figure_artifacts import figure_artifact_registry
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION
from server.services.simulation_publication_registry import simulation_figure_production_route


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[dict]]:
    data = root / "experiments/results/simulated/locked.csv"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"unit,metric\nfixture,0.73\n")
    figures = []
    for index in range(7):
        source = root / f"figures/simulated/registered_{index}.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"raise RuntimeError('This source must not execute in attestation')\n")
        outputs = {kind: source.with_suffix(f".{kind}") for kind in ("pdf", "svg", "png")}
        for path in outputs.values():
            path.write_bytes(b"frozen local artifact fixture")
        figures.append({
            "id": f"synthetic_preview_test_{index}", "producer_kind": "deterministic",
            "source": source.relative_to(root).as_posix(), "source_sha256": _hash(source),
            "outputs": {kind: path.relative_to(root).as_posix() for kind, path in outputs.items()},
            "output_sha256": {kind: _hash(path) for kind, path in outputs.items()},
        })
    manifest = root / attestation.MANIFEST_RELATIVE
    manifest.write_text(json.dumps({
        "schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
        "evidence_status": "synthetic_preview", "simulation_id": "locked-fixture",
        "data_files": [{"path": data.relative_to(root).as_posix(), "sha256": _hash(data)}],
        "figure_files": figures,
    }), encoding="utf-8")
    for figure in figures:
        figure_artifact_registry.record(
            output_dir=root / "figures", figure_type="matplotlib", description="Scientific comparison",
            output_path=str(root / figure["outputs"]["pdf"]), source_path=str(root / figure["source"]),
            metadata={"semantic_key": figure["id"], "producer_kind": "deterministic",
                      "scientific_role": "result", "evidence_status": "synthetic_preview",
                      "provenance_kind": "deterministic_simulation_preview",
                      "simulation_id": "locked-fixture", "paper_selected": False,
                      "source_data": [data.relative_to(root).as_posix()],
                      "source_data_sha256": {data.relative_to(root).as_posix(): _hash(data)},
                      "simulation_manifest_sha256": _hash(manifest)},
        )
    monkeypatch.setattr(attestation, "simulation_manifest_contract_issues", lambda _payload: [])
    return manifest, figures


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_attestation_repairs_runtime_route_only_and_is_byte_stable_on_second_call(tmp_path, monkeypatch):
    manifest, figures = _bundle(tmp_path, monkeypatch)
    specs = [{"id": record["id"], "kind": "figure",
              **simulation_figure_production_route(record)} for record in figures[:6]]
    (tmp_path / "figures/FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "production_policy_schema": 1, "publication_label_schema": 1, "figures": specs,
    }), encoding="utf-8")
    before = _files(tmp_path)
    registered = copy.deepcopy(figure_artifact_registry.load(tmp_path / "figures")["figures"])
    assert len(attestation.attest_existing_simulation_figures(tmp_path)) == 7
    for path, content in before.items():
        if path.name not in {"FIGURE_MANIFEST.json", "FIGURE_MANIFEST.md"}:
            assert path.read_bytes() == content
    current = {item["id"]: item for item in figure_artifact_registry.load(tmp_path / "figures")["figures"]}
    for entry in registered:
        after = current[entry["id"]]
        for key in ("source_path", "source_sha256", "output_path", "output_sha256"):
            assert after[key] == entry[key]
        for key in ("evidence_status", "source_data", "source_data_sha256", "simulation_id", "paper_selected"):
            assert after["metadata"][key] == entry["metadata"][key]
        assert after["metadata"]["production_strategy"] == "deterministic_plot"
        assert after["metadata"]["composition_owner"] == "runtime"
        assert after["metadata"]["recommended_skill"] == "paper-figure"
        assert after["metadata"]["simulation_manifest_sha256"] == _hash(manifest)
    first = _files(tmp_path)
    assert attestation.attest_existing_simulation_figures(tmp_path) == []
    assert _files(tmp_path) == first


@pytest.mark.parametrize("policy", ["generate", "reuse", "skip"])
def test_attestation_preserves_plan_owned_generation_policy_without_registry_churn(tmp_path, monkeypatch, policy):
    _manifest, figures = _bundle(tmp_path, monkeypatch)
    assert len(attestation.attest_existing_simulation_figures(tmp_path)) == 7
    root = tmp_path / "figures"
    asset = figures[0]["id"]
    figure_artifact_registry.curate_to_plan(
        root, {record["id"] for record in figures}, evidence_mode="synthetic_preview",
        planned_assets={asset: {"generation_policy": policy}},
    )
    before = _files(tmp_path)
    monkeypatch.setattr(figure_artifact_registry, "record", lambda **_kwargs: pytest.fail("Valid current metadata must not be re-recorded"))
    assert attestation.attest_existing_simulation_figures(tmp_path) == []
    assert _files(tmp_path) == before
    current = next(item for item in figure_artifact_registry.load(root)["figures"] if item["id"] == asset)
    assert current["metadata"]["generation_policy"] == policy


@pytest.mark.parametrize("policy", [None, "", "unknown", "Reuse"])
def test_invalid_generation_decision_is_rejected_before_runtime_metadata_write(tmp_path, monkeypatch, policy):
    _bundle(tmp_path, monkeypatch)
    path = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["figures"][0]["metadata"]["generation_policy"] = policy
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="invalid generation policy"):
        attestation.attest_existing_simulation_figures(tmp_path)
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["data", "source", "variant", "schema", "renderer", "registry_schema", "missing_registration", "metadata_conflict"])
def test_untrusted_current_bindings_fail_before_any_registry_write(tmp_path, monkeypatch, defect):
    manifest, figures = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    if defect in {"schema", "renderer"}:
        payload["schema" if defect == "schema" else "renderer_version"] -= 1
        manifest.write_text(json.dumps(payload))
    elif defect == "data":
        (tmp_path / payload["data_files"][0]["path"]).write_bytes(b"changed")
    elif defect == "source":
        (tmp_path / figures[0]["source"]).write_bytes(b"changed")
    elif defect == "variant":
        (tmp_path / figures[0]["outputs"]["png"]).write_bytes(b"changed")
    else:
        path = tmp_path / "figures/FIGURE_MANIFEST.json"
        registry = json.loads(path.read_text())
        if defect == "registry_schema":
            registry["schema"] = 2
        elif defect == "missing_registration":
            registry["figures"].pop()
        else:
            registry["figures"][0]["metadata"]["composition_owner"] = "model"
        path.write_text(json.dumps(registry))
    before = _files(tmp_path)
    with pytest.raises(ValueError):
        attestation.attest_existing_simulation_figures(tmp_path)
    assert _files(tmp_path) == before


def test_canonical_producer_conflict_is_not_rewritten(tmp_path, monkeypatch):
    _manifest, figures = _bundle(tmp_path, monkeypatch)
    spec = {"id": figures[0]["id"], "kind": "figure", **simulation_figure_production_route(figures[0])}
    spec["producer_kind"] = "model"
    (tmp_path / "figures/FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "production_policy_schema": 1, "publication_label_schema": 1, "figures": [spec],
    }))
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="conflicts with canonical"):
        attestation.attest_existing_simulation_figures(tmp_path)
    assert _files(tmp_path) == before


def test_partial_registration_failure_rolls_back_both_registry_files(tmp_path, monkeypatch):
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
        attestation.attest_existing_simulation_figures(tmp_path)
    assert calls == 2
    assert _files(tmp_path) == before


def test_concurrent_source_change_rolls_back_runtime_registration(tmp_path, monkeypatch):
    _manifest, figures = _bundle(tmp_path, monkeypatch)
    targets = [tmp_path / "figures/FIGURE_MANIFEST.json", tmp_path / "figures/FIGURE_MANIFEST.md"]
    before = {path: path.read_bytes() for path in targets}
    original = figure_artifact_registry.record

    def change_source_after_registration(**kwargs):
        result = original(**kwargs)
        (tmp_path / figures[0]["source"]).write_bytes(b"concurrent source edit")
        return result

    monkeypatch.setattr(figure_artifact_registry, "record", change_source_after_registration)
    with pytest.raises(ValueError, match="hash mismatch"):
        attestation.attest_existing_simulation_figures(tmp_path)
    assert all(path.read_bytes() == content for path, content in before.items())
