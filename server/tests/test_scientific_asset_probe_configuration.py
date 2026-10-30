"""Actual project config reaches figure authoring without inventing activation."""

import json
from pathlib import Path

from server.services.scientific_asset_builders import design_assets
from server.services.scientific_asset_contract import build_contract_context
from server.services.figure_semantic_projection import project_figure_semantics
from server.workflows.figure_asset_delegates import _active_mechanism_guidance


def test_project_probe_mode_reaches_figure_brief_and_authoring_prompt(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    experiments = tmp_path / "experiments"
    ideas.mkdir()
    (experiments / "configs").mkdir(parents=True)
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "status": "accepted", "title": "Probe study",
        "hypothesis": "Matched masking supports transferable features.",
        "claims": [{"id": "C1", "publication_statement": "Matched features transfer."}],
        "mechanisms": [{
            "id": "M1", "publication_name": "Masked prediction",
            "publication_description": "Predict masked observations.",
        }, {
            "id": "M2", "publication_name": "Identity attribution",
            "publication_description": "Evaluate source identity shortcuts.",
        }],
        "publication": {"language": "en", "method_name": "Masked method",
                        "contribution_type": "objective_mechanism"},
    }), encoding="utf-8")
    (experiments / "METHOD_CONTRACT.json").write_text(json.dumps({
        "schema": 2, "status": "implemented",
        "scientific_scene": {
            "schema": 1,
            "objects": [{"id": "source", "kind": "input", "label": "Signal",
                         "source_path": "ideas/SELECTED_IDEA.json"},
                        {"id": "prediction", "kind": "operation", "label": "Masked prediction",
                         "source_path": "experiments/METHOD_CONTRACT.json"}],
            "relations": [{"from": "source", "to": "prediction", "kind": "data"}],
        },
    }), encoding="utf-8")
    (experiments / "RUN_SPEC.json").write_text(json.dumps({
        "schema": 1, "command": "python experiments/src/train.py --config experiments/configs/main.yaml",
    }), encoding="utf-8")
    config = experiments / "configs" / "main.yaml"
    config.write_text(
        "model:\n  subject_classes: null\n  session_classes: null\n"
        "objective:\n  subject_probe_weight: 0.0\n  session_probe_weight: 0.0\n"
        "ablations:\n  subject_session_probe:\n    mechanism_id: M2\n    enabled: true\n",
        encoding="utf-8",
    )
    context = build_contract_context(tmp_path, lambda *_args: {})
    assets = design_assets(context, {}, True)
    asset = next(item for item in assets if item["id"] == "method_architecture")
    assert "experiments/configs/main.yaml" in asset["source_data"]
    state = project_figure_semantics(asset)["probe_configuration"][0]
    assert state["training_mode"] == "unspecified"
    assert state["joint_objective_status"] == "inactive"
    assert "joint training not established" in _active_mechanism_guidance(asset)

    config.write_text(config.read_text(encoding="utf-8") + "    mode: frozen_downstream\n",
                      encoding="utf-8")
    updated = build_contract_context(tmp_path, lambda *_args: {})
    updated_asset = next(item for item in design_assets(updated, {}, True)
                         if item["id"] == "method_architecture")
    assert "not a joint GRL loss" in _active_mechanism_guidance(updated_asset)
