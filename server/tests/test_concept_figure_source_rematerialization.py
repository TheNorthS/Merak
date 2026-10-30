"""Current concept sources rematerialize from their owner; stale acceptance is not re-signed."""

from copy import deepcopy
import hashlib
import json

import pytest

from server.services.scientific_assets import scientific_asset_service, ARCHETYPE_PLOT_ROLES
from server.services.scientific_asset_builders import design_assets
from server.services.scientific_asset_routing import route_scientific_assets
from server.services.figure_spec_repository import persist_figure_specs
from server.services.figure_generation_transaction import _source_bindings
from server.services.deterministic_figure_builder import _current_entry_reusable, ensure_evaluation_design
from server.services.figure_engine import FigureType, figure_engine
from server.services.figure_models import FigureResult
from server.services.figure_producer_errors import DeterministicFigureProducerError
from server.tests.test_deterministic_architecture_integration import _asset, _Registry, _Host


def _project(root):
    paths = ["ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json",
             "experiments/EXPERIMENT_PLAN.md", "experiments/configs/main.yaml"]
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
    selected = {"schema": 2, "title": "Source-bound patch representation", "hypothesis": "A registered representation hypothesis.",
                "publication": {"title": "Source-bound patch representation", "method_name": "Patch model",
                    "language": "en", "contribution_type": "model_architecture", "comparator_names": ["Matched reference"]},
                "claims": [{"id": "C1", "publication_statement": "The representation is tested under matched conditions."}],
                "mechanisms": [{"id": "M1", "publication_name": "Patch encoder",
                    "publication_description": "Transform patch inputs into a registered representation.",
                    "publication_evaluation": "Matched held-out comparison"}]}
    scene = deepcopy(_asset()["scientific_scene"])
    old = root / "experiments/src/models.py"
    old.parent.mkdir()
    old.write_text("class OldEncoder:\n    def forward(self,x):\n        return x\n")
    method = {"schema": 2, "scientific_scene": scene, "implementation_family": "machine_learning",
              "implementation_checks": [{"id": "M1-CODE", "description": "Declared encoder source", "evidence": [
                  {"path": "experiments/src/models.py", "symbols": ["OldEncoder"]}]}]}
    (root / paths[0]).write_text(json.dumps(selected))
    (root / paths[1]).write_text(json.dumps(method))
    (root / paths[2]).write_text(json.dumps({"entrypoint": "experiments/src/train.py"}))
    (root / paths[3]).write_text("Registered method and evaluation protocol.")
    (root / paths[4]).write_text("model: {backbone: declared_encoder}\n")
    return old, method


def test_current_source_inventory_replaces_old_paths_without_inventing_scientific_edges_or_changing_numeric_data(tmp_path):
    old, method = _project(tmp_path)
    numeric = tmp_path / "experiments/results/simulated"
    numeric.mkdir(parents=True)
    for index in range(7):
        (numeric / f"registered-{index}.csv").write_text(f"seed,value\n13,{index}\n")
    before = {path: path.read_bytes() for path in numeric.glob("*.csv")}
    first = scientific_asset_service._contract_context(tmp_path)
    assert "experiments/src/models.py" in first["source_artifacts"]
    old.unlink()
    new = tmp_path / "experiments/src/current_package/models.py"
    new.parent.mkdir()
    new.write_text("class CurrentEncoder:\n    def forward(self,x):\n        return x\n")
    method["implementation_checks"][0]["evidence"] = [
        {"path": "experiments/src/current_package/models.py", "symbols": ["CurrentEncoder"]}]
    (tmp_path / "experiments/METHOD_CONTRACT.json").write_text(json.dumps(method))
    context = scientific_asset_service._contract_context(tmp_path)
    assert "experiments/src/current_package/models.py" in context["source_artifacts"]
    assert "experiments/src/models.py" not in context["source_artifacts"]
    assert all((tmp_path / path).is_file() for path in context["source_artifacts"])
    assets = design_assets(context, context["architecture_blueprint"], True,
                           publication_style={"family": "machine_learning", "study_archetype": "algorithm_benchmark"})
    route_scientific_assets(assets, {"family": "machine_learning", "study_archetype": "algorithm_benchmark"}, "", ARCHETYPE_PLOT_ROLES)
    plan = {"assets": assets, "evidence_mode": "synthetic_preview"}
    specs = persist_figure_specs(tmp_path, plan)
    method_spec = next(item for item in specs if item["id"] == "method_architecture")
    assert method_spec["scientific_scene"] == method["scientific_scene"]
    assert method_spec["source_data"] == context["source_artifacts"]
    assert {(row["from"], row["to"], row["kind"]) for row in method_spec["scientific_scene"]["relations"]} == {
        (row["from"], row["to"], row["kind"]) for row in method["scientific_scene"]["relations"]}
    assert {path: path.read_bytes() for path in numeric.glob("*.csv")} == before
    assert not old.exists()


def test_old_accepted_source_binding_is_not_reusable_after_owner_source_moves(tmp_path):
    old, _method = _project(tmp_path)
    metadata = {"producer_kind": "deterministic", "producer_input_sha256": "current-input",
                "source_data": ["experiments/src/models.py"]}
    metadata["source_bindings"] = _source_bindings(metadata, tmp_path, lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
    old.unlink()
    entry = {"metadata": metadata}
    original = deepcopy(entry)
    assert not _current_entry_reusable(entry, tmp_path, "current-input")
    assert entry == original and not old.exists()


@pytest.mark.asyncio
async def test_rejected_current_concept_regeneration_preserves_old_entry_not_false_acceptance(tmp_path, monkeypatch):
    figures = tmp_path / "figures"
    figures.mkdir()
    registry, host = _Registry(), _Host()
    registry.figures = [{"id": "method_architecture", "metadata": {"producer_kind": "deterministic",
        "producer_input_sha256": "old-owner-source", "source_data": ["experiments/src/obsolete.py"]}}]
    original = deepcopy(registry.figures)
    calls = []

    async def reject(**arguments):
        calls.append(arguments)
        return FigureResult(False, FigureType.FIGURESPEC, error="Current source renderer rejected by real producer boundary")

    monkeypatch.setattr(figure_engine, "generate", reject)
    asset = _asset()
    asset["source_data"] = ["experiments/METHOD_CONTRACT.json"]
    with pytest.raises(DeterministicFigureProducerError, match="renderer rejected"):
        await ensure_evaluation_design(host, object(), figures, [asset], {}, set(), registry)
    assert len(calls) == 1 and calls[0]["metadata"]["producer_input_sha256"] != "old-owner-source"
    assert registry.figures == original and not (tmp_path / "experiments/src/obsolete.py").exists()
