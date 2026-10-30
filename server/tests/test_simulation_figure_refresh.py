"""Local refresh transactions preserve evidence and refuse stale source bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services import simulation_figure_refresh as refresh
from server.services import simulation_publication_attestation as attestation
from server.services.figure_artifacts import figure_artifact_registry
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION,
)
from server.tests.test_simulation_comparison_layout import _fixture_rows


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data = tmp_path / "experiments/results/simulated/main_comparison.csv"
    _fixture_rows(data, 6, 8)
    source = tmp_path / "figures/simulated/simulated_main_comparison.py"
    source.parent.mkdir(parents=True)
    source.write_text("# previous canonical layout fixture\n", encoding="utf8")
    outputs = {kind: source.with_suffix(f".{kind}") for kind in ("pdf", "svg", "png")}
    for path in outputs.values():
        path.write_bytes(b"previous variant fixture")
    record = {
        "id": refresh._PRIMARY_ID, "producer_kind": "deterministic",
        "source": source.relative_to(tmp_path).as_posix(),
        "source_sha256": _hash(source),
        "outputs": {kind: path.relative_to(tmp_path).as_posix() for kind, path in outputs.items()},
        "output_sha256": {kind: _hash(path) for kind, path in outputs.items()},
    }
    payload = {
        "schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
        "simulation_id": "immutable-layout-fixture", "simulation_seed": "13",
        "evidence_status": "synthetic_preview", "replicate_contract": {"seed_ids": [13, 42, 73]},
        "specialized_domain": "vision", "primary_metric": "macro_f1", "metric_direction": "maximize",
        "data_files": [{"path": data.relative_to(tmp_path).as_posix(), "sha256": _hash(data)}],
        "figure_files": [record], "domain_asset_profile": [{
            "semantic_id": refresh._PRIMARY_ID, "data_file": data.name,
            "analysis_subtype": "cross_dataset_task_matrix",
        }],
    }
    manifest = tmp_path / refresh._MANIFEST
    manifest.write_text(json.dumps(payload), encoding="utf8")
    style = tmp_path / "paper/PUBLICATION_STYLE.json"
    style.parent.mkdir()
    style.write_text(json.dumps({"fonts": ["DejaVu Sans"], "canvas": {"png_dpi": 200}}))
    figure_artifact_registry.record(
        output_dir=tmp_path / "figures", figure_type="matplotlib", description="Registered comparison",
        output_path=str(outputs["pdf"]), source_path=str(source), metadata={
            "semantic_key": refresh._PRIMARY_ID, "scientific_role": "result",
            "producer_kind": "deterministic",
            "simulation_id": "immutable-layout-fixture",
            "evidence_status": "synthetic_preview", "provenance_kind": "deterministic_simulation_preview",
            "source_data": [data.relative_to(tmp_path).as_posix()],
            "source_data_sha256": {data.relative_to(tmp_path).as_posix(): _hash(data)},
            "simulation_manifest_sha256": _hash(manifest),
        },
    )
    # Contract-field validation is covered separately; these fixtures isolate
    # filesystem and render transactions instead of generating a benchmark.
    monkeypatch.setattr(refresh, "simulation_manifest_contract_issues", lambda _payload: [])
    monkeypatch.setattr(attestation, "simulation_manifest_contract_issues", lambda _payload: [])
    return data, manifest


async def _render_local(script: Path) -> tuple[bool, str]:
    namespace = {"__file__": str(script), "__name__": "__local_render_fixture__"}
    exec(compile(script.read_text(encoding="utf8"), str(script), "exec"), namespace)
    return True, ""


@pytest.mark.asyncio
async def test_refresh_preserves_data_and_identity_and_reuses_second_call(tmp_path, monkeypatch):
    data, manifest = _bundle(tmp_path, monkeypatch)
    before_data = data.read_bytes()
    before = json.loads(manifest.read_text())
    calls = []

    async def render(script):
        calls.append(script)
        assert script.is_relative_to(tmp_path / ".merak/transactions")
        return await _render_local(script)

    assert await refresh.refresh_existing_simulation_figures(tmp_path, render_script=render) == [refresh._PRIMARY_ID]
    assert len(calls) == 1 and data.read_bytes() == before_data
    after = json.loads(manifest.read_text())
    assert {key: value for key, value in before.items() if key != "figure_files"} == {
        key: value for key, value in after.items() if key != "figure_files"
    }
    record = after["figure_files"][0]
    assert record["source_sha256"] == record["render_code_sha256"]
    assert all(_hash(tmp_path / path) == record["output_sha256"][kind]
               for kind, path in record["outputs"].items())
    entry = figure_artifact_registry.load(tmp_path / "figures")["figures"][0]
    assert entry["metadata"]["simulation_manifest_sha256"] == _hash(manifest)
    assert entry["metadata"]["source_data_sha256"] == {data.relative_to(tmp_path).as_posix(): _hash(data)}
    assert await refresh.refresh_existing_simulation_figures(tmp_path, render_script=render) == []
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["data", "source", "duplicate", "escape"])
@pytest.mark.asyncio
async def test_refresh_refuses_untrusted_inputs_before_render(tmp_path, monkeypatch, mutation):
    data, manifest = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    if mutation == "data":
        data.write_bytes(data.read_bytes() + b"changed")
    elif mutation == "source":
        (tmp_path / payload["figure_files"][0]["source"]).write_text("changed")
    elif mutation == "duplicate":
        payload["figure_files"].append(payload["figure_files"][0])
    else:
        payload["figure_files"][0]["source"] = "../outside.py"
    manifest.write_text(json.dumps(payload))

    async def forbidden(_script):
        pytest.fail("Untrusted input must fail before rendering")

    with pytest.raises(ValueError):
        await refresh.refresh_existing_simulation_figures(tmp_path, render_script=forbidden)


@pytest.mark.asyncio
async def test_failed_render_does_not_change_canonical_files(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for folder in (tmp_path / "figures", tmp_path / "experiments")
              for path in folder.rglob("*") if path.is_file()}

    async def fail(_script):
        return False, "renderer fixture failed"

    with pytest.raises(RuntimeError, match="renderer fixture failed"):
        await refresh.refresh_existing_simulation_figures(tmp_path, render_script=fail)
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.asyncio
async def test_failed_registration_rolls_back_source_variants_and_manifests(tmp_path, monkeypatch):
    _bundle(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for folder in (tmp_path / "figures", tmp_path / "experiments")
              for path in folder.rglob("*") if path.is_file()}

    def fail(*_args, **_kwargs):
        raise RuntimeError("registration fixture failed")

    monkeypatch.setattr(figure_artifact_registry, "record", fail)
    with pytest.raises(RuntimeError, match="registration fixture failed"):
        await refresh.refresh_existing_simulation_figures(tmp_path, render_script=_render_local)
    assert all(path.read_bytes() == content for path, content in before.items())
