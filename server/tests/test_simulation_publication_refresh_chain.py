"""Current complete finite bundles survive real render-to-paper producer refresh."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services import simulation_figure_refresh as refresh
from server.services.figure_artifacts import figure_artifact_registry
from server.services.paper_artifacts import simulation_manifest_semantic_hash
from server.services.planned_simulation_bindings import load_planned_simulation_binding
from server.services.simulation_paper_projection import refresh_simulation_paper_projection
from server.services.simulation_policy import simulation_manifest_contract_issues
from server.tests._scientific_slide_fixture import write_current_publication_table_bundle
from server.tests._publication_refresh_fixture import bind_fixture_primary_table
from server.tests.test_simulation_comparison_layout import _fixture_rows
from server.tests.test_simulation_figure_refresh import _render_local
from server.workflows.models import WorkflowRun
from server.workflows.simulation_render_refresh import refresh_simulation_renderer


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _complete_bundle(root: Path, method_count: int = 3, dataset_count: int = 3,
                     direction: str = "Finite local benchmark") -> tuple[Path, Path]:
    """Use finite constants and real current contracts; no owner gate is mocked."""
    paths = write_current_publication_table_bundle(root)
    manifest = paths["simulation_manifest"]
    payload = json.loads(manifest.read_text())
    primary = next(item for item in payload["figure_files"] if item["id"] == refresh._PRIMARY_ID)
    data = root / "experiments/results/simulated/main_comparison.csv"
    seed = root / "finite-row-seed/main_comparison.csv"
    _fixture_rows(seed, method_count, dataset_count)
    data.write_bytes(seed.read_bytes())
    payload.update(specialized_domain="vision", primary_metric="macro_f1")
    for record in payload["figure_files"]:
        record["label"] = "fig:" + record["id"]
    primary["analysis_subtype"] = "cross_dataset_task_matrix"
    for profile in payload["domain_asset_profile"]:
        if profile["semantic_id"] == refresh._PRIMARY_ID:
            profile["analysis_subtype"] = "cross_dataset_task_matrix"
    for record in payload["data_files"]:
        record["sha256"] = _hash(root / record["path"])
    bind_fixture_primary_table(root, payload)
    paper = root / "paper/synthetic_preview_figures.tex"
    payload.update(paper_figures=paper.relative_to(root).as_posix(), paper_figures_sha256=_hash(paper))
    assert simulation_manifest_contract_issues(payload) == []
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    (root / "paper/PUBLICATION_STYLE.json").write_text(json.dumps({
        "fonts": ["DejaVu Sans"], "canvas": {"png_dpi": 200},
    }))
    previous = {entry["id"]: entry for entry in figure_artifact_registry.load(root / "figures")["figures"]}
    for record in payload["figure_files"]:
        metadata = {**previous[record["id"]]["metadata"], "label": record["label"],
                    "simulation_manifest_sha256": _hash(manifest), "caption": "Finite scientific comparison"}
        if record["id"] == refresh._PRIMARY_ID:
            metadata["scientific_role"] = "result"
        metadata["source_data_sha256"] = {value: _hash(root / value) for value in metadata["source_data"]}
        figure_artifact_registry.record(output_dir=root / "figures", figure_type="matplotlib",
                                        description="Finite scientific comparison", metadata=metadata,
                                        source_path=str(root / record["source"]),
                                        output_path=str(root / record["outputs"]["pdf"]))
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    planned.parent.mkdir(parents=True)
    from server.services.evidence_versions import version_plan
    identity = version_plan(root, direction, {"non_experiment_evidence_mode": "synthetic_preview"})
    planned.write_text(json.dumps({"schema": 5, "simulation_manifest": refresh._MANIFEST,
                                  "input_bundle_sha256": identity["input_sha256"],
                                  "simulation_manifest_sha256": _hash(manifest),
                                  "figures": figure_artifact_registry.load(root / "figures")["figures"]}))
    return manifest, planned


class _Host:
    def __init__(self) -> None:
        self.events = []

    async def _emit(self, _run, event, payload):
        self.events.append((event, payload))


@pytest.mark.asyncio
async def test_real_primary_then_paper_projection_updates_every_binding_and_is_byte_stable(tmp_path, monkeypatch):
    manifest, planned = _complete_bundle(tmp_path)
    before = _files(tmp_path)
    scientific = json.loads(manifest.read_text())
    planned_before = json.loads(planned.read_text())
    actual = refresh.refresh_existing_simulation_figures
    calls = []

    async def current_producer(root):
        async def render(script):
            calls.append(script)
            return await _render_local(script)
        return await actual(root, render_script=render)

    monkeypatch.setattr(refresh, "refresh_existing_simulation_figures", current_producer)
    run = WorkflowRun(project_path=str(tmp_path), options={
        "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
    })
    assert await refresh_simulation_renderer(_Host(), run, "Finite local benchmark")
    assert len(calls) == 1
    after = json.loads(manifest.read_text())
    assert simulation_manifest_contract_issues(after) == []
    assert simulation_manifest_semantic_hash(after) == simulation_manifest_semantic_hash(scientific)
    load_planned_simulation_binding(tmp_path, _hash(manifest), after["figure_files"])
    for record in scientific["data_files"]:
        assert (tmp_path / record["path"]).read_bytes() == before[tmp_path / record["path"]]
    for record in scientific["figure_files"]:
        if record["id"] != refresh._PRIMARY_ID:
            for relative in (record["source"], *record["outputs"].values()):
                assert (tmp_path / relative).read_bytes() == before[tmp_path / relative]
    changed = json.loads(planned.read_text())
    assert {key: value for key, value in changed.items() if key not in {"simulation_manifest_sha256", "figures"}} == {
        key: value for key, value in planned_before.items() if key not in {"simulation_manifest_sha256", "figures"}
    }
    first = _files(tmp_path)
    assert not await refresh_simulation_renderer(_Host(), run, "Finite local benchmark")
    assert len(calls) == 1 and _files(tmp_path) == first


@pytest.mark.asyncio
async def test_accepted_plan_reuse_survives_no_change_refresh_with_every_byte_stable(tmp_path, monkeypatch):
    from server.services.evidence_asset_portfolio import selected_evidence_asset_ids
    from server.services.simulation_comparison_plots import _multitask_matrix_script
    from server.services.publication_labels import publication_metric_label

    manifest, _planned = _complete_bundle(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    primary = next(item for item in payload["figure_files"] if item["id"] == refresh._PRIMARY_ID)
    data, relative = refresh._primary_input(tmp_path, payload, primary)
    style = json.loads((tmp_path / "paper/PUBLICATION_STYLE.json").read_text(encoding="utf-8"))
    code = _multitask_matrix_script(data.relative_to(tmp_path).as_posix(),
                                   publication_metric_label(payload["primary_metric"]),
                                   refresh._PRIMARY_STEM, style, payload["metric_direction"])
    (tmp_path / relative).write_bytes(code.encode("utf-8"))
    assert (tmp_path / relative).read_bytes() == code.encode("utf-8")
    primary["source_sha256"] = _hash(tmp_path / relative)
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    registry = tmp_path / "figures/FIGURE_MANIFEST.json"
    registered = json.loads(registry.read_text(encoding="utf-8"))
    for item in registered["figures"]:
        item["metadata"]["simulation_manifest_sha256"] = _hash(manifest)
        if item["id"] == refresh._PRIMARY_ID:
            item["source_sha256"] = primary["source_sha256"]
    registry.write_text(json.dumps(registered), encoding="utf-8")
    planned = tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    binding = json.loads(planned.read_text(encoding="utf-8"))
    binding["simulation_manifest_sha256"] = _hash(manifest)
    binding["figures"] = registered["figures"]
    planned.write_text(json.dumps(binding), encoding="utf-8")
    assert refresh_simulation_paper_projection(tmp_path)
    from server.services.simulation_table_publication_refresh import refresh_simulation_publication_tables
    refresh_simulation_publication_tables(tmp_path)
    selected = selected_evidence_asset_ids("objective_mechanism")
    figure_artifact_registry.curate_to_plan(
        tmp_path / "figures", selected, evidence_mode="synthetic_preview",
        planned_assets={identity: {"generation_policy": "reuse",
                                  "scientific_role": "result" if identity == refresh._PRIMARY_ID
                                  else identity.removeprefix("synthetic_preview_")}
                        for identity in selected},
    )
    curated = figure_artifact_registry.load(tmp_path / "figures")["figures"]
    assert {item["id"] for item in curated if item["metadata"]["paper_selected"]} == selected
    assert all(item["paper_ready"] is (item["id"] in selected) for item in curated)
    before = _files(tmp_path)

    async def forbidden(_script):
        pytest.fail("Identical source and current pixels must not execute a renderer")

    monkeypatch.setattr(refresh, "render_simulation_script", forbidden)
    actual = refresh.refresh_existing_simulation_figures

    async def no_render(root):
        return await actual(root, render_script=forbidden)

    monkeypatch.setattr(refresh, "refresh_existing_simulation_figures", no_render)
    run = WorkflowRun(project_path=str(tmp_path), options={
        "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
    })
    host = _Host()
    assert not await refresh_simulation_renderer(host, run, "Finite local benchmark")
    assert not await refresh_simulation_renderer(host, run, "Finite local benchmark")
    assert host.events == [] and _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["data", "planned_top", "planned_embedded", "planned_source", "planned_variant", "semantic_key"])
@pytest.mark.asyncio
async def test_untrusted_complete_binding_is_rejected_before_render_and_canonical_writes(tmp_path, defect):
    manifest, planned = _complete_bundle(tmp_path)
    payload = json.loads(manifest.read_text())
    if defect == "data":
        (tmp_path / payload["data_files"][0]["path"]).write_bytes(b"changed")
    elif defect == "semantic_key":
        registry = tmp_path / "figures/FIGURE_MANIFEST.json"
        content = json.loads(registry.read_text())
        content["figures"][0]["metadata"]["semantic_key"] = content["figures"][1]["id"]
        registry.write_text(json.dumps(content))
    else:
        content = json.loads(planned.read_text())
        if defect == "planned_top":
            content["simulation_manifest_sha256"] = "0" * 64
        elif defect == "planned_embedded":
            content["figures"][0]["metadata"]["simulation_manifest_sha256"] = "0" * 64
        elif defect == "planned_source":
            content["figures"][0]["source_sha256"] = "0" * 64
        else:
            content["figures"][0]["metadata"]["rendered_variant_sha256"]["png"] = "0" * 64
        planned.write_text(json.dumps(content))
    before = _files(tmp_path)

    async def forbidden(_script):
        pytest.fail("Stale owner bindings must fail before any local rendering")

    with pytest.raises(ValueError):
        await refresh.refresh_existing_simulation_figures(tmp_path, render_script=forbidden)
    assert _files(tmp_path) == before


@pytest.mark.asyncio
async def test_primary_commit_failure_restores_planned_registry_source_and_variants(tmp_path, monkeypatch):
    from server.services import simulation_figure_refresh as service

    _manifest, planned = _complete_bundle(tmp_path)
    before = _files(tmp_path)
    original = service.atomic_write_json

    def fail_at_planned(path, payload):
        if Path(path) == planned:
            raise RuntimeError("finite planned commit failure")
        return original(path, payload)

    monkeypatch.setattr(service, "atomic_write_json", fail_at_planned)
    with pytest.raises(RuntimeError, match="finite planned commit failure"):
        await service.refresh_existing_simulation_figures(tmp_path, render_script=_render_local)
    assert _files(tmp_path) == before
