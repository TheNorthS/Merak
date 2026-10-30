"""Workflow adapters reuse trusted evidence and invoke render-only refresh."""

from __future__ import annotations

import json
import ast
from pathlib import Path

import pytest

from server.services import simulation_figure_refresh
from server.services.experiment_placeholders import experiment_placeholder_service
from server.services.project_scaffold import get_convention_paths
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION, SIMULATION_STABLE_ROLES,
)
from server.tests.test_simulation_figure_refresh import _bundle, _render_local
from server.workflows.engine_inputs import InputsMixin
from server.workflows.models import WorkflowRun
from server.workflows.simulation_render_refresh import refresh_simulation_renderer


class _Host(InputsMixin):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def _emit(self, _run: object, event: str, payload: dict) -> None:
        self.events.append((event, payload))


def _run(root: Path, **options: object) -> WorkflowRun:
    return WorkflowRun(
        id="fixture-render-recovery", project_path=str(root), checkpoint_node_id="figure",
        options={"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview", **options},
    )


def _forbid_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services import simulation_paper_projection

    async def forbidden(*_args: object, **_kwargs: object) -> dict:
        pytest.fail("Existing evidence must not be regenerated for a current renderer repair")

    monkeypatch.setattr(experiment_placeholder_service, "ensure", forbidden)
    # These partial bundles isolate the render adapter. The paper-projection
    # producer has complete-binding, rollback and no-regeneration regressions.
    monkeypatch.setattr(simulation_paper_projection, "refresh_simulation_paper_projection", lambda _root: False)


@pytest.mark.asyncio
async def test_prevalidation_adapter_uses_real_refresh_and_second_pass_is_stable(tmp_path, monkeypatch):
    from server.tests.test_simulation_publication_refresh_chain import _complete_bundle

    manifest, _planned = _complete_bundle(tmp_path, method_count=6, dataset_count=8, direction="Fixture direction")
    data = tmp_path / "experiments/results/simulated/main_comparison.csv"
    before_data = data.read_bytes()
    before = json.loads(manifest.read_text())
    original_refresh = simulation_figure_refresh.refresh_existing_simulation_figures

    async def local_refresh(root):
        return await original_refresh(root, render_script=_render_local)

    monkeypatch.setattr(simulation_figure_refresh, "refresh_existing_simulation_figures", local_refresh)
    _forbid_generation(monkeypatch)
    host = _Host()
    run = _run(tmp_path)
    assert await host._refresh_simulation_renderer_before_revalidation(run, "Fixture direction")
    assert not await host._refresh_simulation_renderer_before_revalidation(run, "Fixture direction")
    assert data.read_bytes() == before_data
    after = json.loads(manifest.read_text())
    assert {key: value for key, value in before.items() if key != "figure_files"} == {
        key: value for key, value in after.items() if key != "figure_files"
    }
    assert host.events == [("simulation_figure_rendering_refreshed", {
        "node_id": "figure", "asset_ids": [simulation_figure_refresh._PRIMARY_ID],
        "scientific_data_changed": False,
        "table_projection_changed": True,
    })]


@pytest.mark.parametrize("options", [
    {"run_experiment": True}, {"non_experiment_evidence_mode": "existing_results"},
    {"non_experiment_evidence_mode": "design_only"},
])
@pytest.mark.asyncio
async def test_adapter_does_not_touch_unrelated_evidence_modes(tmp_path, monkeypatch, options):
    _forbid_generation(monkeypatch)

    async def forbidden(_root):
        pytest.fail("Rendering refresh must not touch unrelated evidence modes")

    monkeypatch.setattr(simulation_figure_refresh, "refresh_existing_simulation_figures", forbidden)
    assert not await refresh_simulation_renderer(_Host(), _run(tmp_path, **options), "Fixture")


@pytest.mark.asyncio
async def test_schema_failure_is_not_converted_to_regenerated_evidence(tmp_path, monkeypatch):
    _data, manifest = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    payload["schema"] = SIMULATION_MANIFEST_SCHEMA - 1
    manifest.write_text(json.dumps(payload))
    before = manifest.read_bytes()
    _forbid_generation(monkeypatch)
    with pytest.raises(ValueError, match="Unsupported simulation schema"):
        await refresh_simulation_renderer(_Host(), _run(tmp_path), "Fixture")
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("content", [b"{broken", b"[1, 2]", b"\xff\xfeinvalid"])
@pytest.mark.asyncio
async def test_existing_manifest_failure_preserves_data_instead_of_regenerating(tmp_path, monkeypatch, content):
    data, manifest = _bundle(tmp_path, monkeypatch)
    before_data = data.read_bytes()
    manifest.write_bytes(content)
    _forbid_generation(monkeypatch)
    with pytest.raises(ValueError, match="Existing simulation manifest"):
        await refresh_simulation_renderer(_Host(), _run(tmp_path), "Fixture")
    assert manifest.read_bytes() == content
    assert data.read_bytes() == before_data


@pytest.mark.asyncio
async def test_missing_manifest_does_not_run_render_recovery(tmp_path, monkeypatch):
    _forbid_generation(monkeypatch)
    assert not await refresh_simulation_renderer(_Host(), _run(tmp_path), "Fixture")


@pytest.mark.parametrize("renderer", [None, True, False, "18", {},
                                     SIMULATION_RENDERER_VERSION - 1,
                                     SIMULATION_RENDERER_VERSION + 1])
@pytest.mark.asyncio
async def test_renderer_failure_is_not_converted_to_regenerated_evidence(tmp_path, monkeypatch, renderer):
    _data, manifest = _bundle(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    if renderer is None:
        payload.pop("renderer_version")
    else:
        payload["renderer_version"] = renderer
    manifest.write_text(json.dumps(payload))
    before = manifest.read_bytes()
    _forbid_generation(monkeypatch)
    with pytest.raises(ValueError, match="renderer version"):
        await refresh_simulation_renderer(_Host(), _run(tmp_path), "Fixture")
    assert manifest.read_bytes() == before


def _planned_cache(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from server.tests._scientific_slide_fixture import write_current_publication_table_bundle

    write_current_publication_table_bundle(root)
    paths = get_convention_paths(root)
    files = [Path(paths[key]) for key in (
        "planned_result_readme", "planned_main_comparison", "planned_ablation",
        "planned_robustness", "planned_result_tables_tex",
    )]
    files += [root / value for value in (
        "experiments/results/templates/calibration_risk_coverage.csv",
        "experiments/results/templates/efficiency.csv",
        "figures/previews/calibration_risk_coverage_preview.py",
        "paper/PUBLICATION_STYLE.json", "paper/synthetic_preview_figures.tex",
    )]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"local cache fixture\n")
    claim = root / "experiments/results/simulated/claim_evidence.csv"
    claim.write_text("claim_id,decision\nC1,fixture-only\n", encoding="utf-8")
    manifest = root / simulation_figure_refresh._MANIFEST
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    import hashlib
    payload["data_files"].append({"path": claim.relative_to(root).as_posix(),
                                 "sha256": hashlib.sha256(claim.read_bytes()).hexdigest()})
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    registry_path = root / "figures/FIGURE_MANIFEST.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for entry in registry["figures"]:
        entry["metadata"]["simulation_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    planned = {"schema": 5, "evidence_mode": "synthetic_preview", "input_bundle_sha256": "fixture-input",
               "publication_style": {"target_venue": "unspecified"}}
    Path(paths["planned_result_manifest"]).write_text(json.dumps(planned), encoding="utf-8")
    monkeypatch.setattr(experiment_placeholder_service, "input_bundle_sha256", lambda *_a, **_k: "fixture-input")
    return paths


@pytest.mark.asyncio
async def test_cached_templates_call_refresh_without_data_regeneration(tmp_path, monkeypatch):
    paths = _planned_cache(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in (tmp_path / "experiments").rglob("*.csv")}
    _forbid_generation(monkeypatch)
    calls = []

    async def refresh(root):
        calls.append(root)
        return [simulation_figure_refresh._PRIMARY_ID]

    monkeypatch.setattr(simulation_figure_refresh, "refresh_existing_simulation_figures", refresh)
    host = _Host()
    run = _run(tmp_path)
    planned = await host._ensure_planned_result_templates(run, "Fixture direction")
    assert calls == [tmp_path]
    assert planned["input_bundle_sha256"] == "fixture-input"
    assert run.options["planned_result_manifest"] == paths["planned_result_manifest"]
    assert all(path.read_bytes() == content for path, content in before.items())
    assert host.events[0][0] == "simulation_figure_rendering_refreshed"


@pytest.mark.asyncio
async def test_cached_render_rejection_does_not_trigger_generator(tmp_path, monkeypatch):
    _planned_cache(tmp_path, monkeypatch)
    _forbid_generation(monkeypatch)

    async def reject(_root):
        raise ValueError("source binding hash mismatch")

    monkeypatch.setattr(simulation_figure_refresh, "refresh_existing_simulation_figures", reject)
    with pytest.raises(ValueError, match="source binding hash mismatch"):
        await _Host()._ensure_planned_result_templates(_run(tmp_path), "Fixture direction")


def test_snapshot_execution_guards_fail_even_without_await() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/verify_figure_snapshot.py"
    parsed = ast.parse(script.read_text(encoding="utf8"))
    function = next(item for item in ast.walk(parsed)
                    if isinstance(item, ast.FunctionDef) and item.name == "forbidden")
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 str(script), "exec"), namespace)
    with pytest.raises(RuntimeError, match="scientific execution is prohibited"):
        namespace["forbidden"]()
