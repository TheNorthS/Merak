from server.services.figure_preflight import figure_preflight_findings


def test_missing_method_source_mapping_routes_to_exp_design() -> None:
    findings = figure_preflight_findings({
        "id": "method_architecture", "kind": "figure", "producer_kind": "model",
        "scientific_scene": {"objects": [{"id": "method", "label": "Method"}]},
        "architecture_blueprint": {"components": []},
    })
    assert findings[0]["owner_node"] == "exp-design"
    assert findings[0]["repair_capability"] == "figure-source-mapping"


def test_source_bound_method_scene_passes_preflight() -> None:
    assert figure_preflight_findings({
        "id": "method_architecture", "kind": "figure", "producer_kind": "model",
        "scientific_scene": {"objects": [{
            "id": "method", "label": "Method",
            "source_path": "experiments/METHOD_CONTRACT.json",
        }]},
        "architecture_blueprint": {"components": []},
    }) == []


def test_scene_complexity_routes_to_figure_layout_owner() -> None:
    findings = figure_preflight_findings({
        "id": "evaluation_design", "kind": "figure", "producer_kind": "model",
        "scientific_scene": {"objects": [{"id": str(index)} for index in range(9)]},
        "scene_contract": {"maximum_primary_nodes": 8},
        "layout_plan": {"split_required": False},
    })
    assert findings[0]["owner_node"] == "figure"
    assert findings[0]["repair_capability"] == "figure-layout"


def test_incomplete_method_path_routes_to_implementation_owner() -> None:
    findings = figure_preflight_findings({
        "id": "method_architecture", "kind": "figure", "producer_kind": "model",
        "scientific_scene": {"objects": [{
            "id": "method", "source_path": "experiments/METHOD_CONTRACT.json",
        }]},
        "architecture_blueprint": {
            "components": [{
                "id": "encoder", "source_path": "experiments/src/models.py",
                "source_symbol": "Encoder",
            }],
            "completeness_issues": [
                "predictive evaluation is declared but no classifier/task head is implemented",
            ],
        },
    })
    finding = next(item for item in findings if "complete scientific path" in item["message"])
    assert finding["owner_node"] == "exp-design"
    assert finding["repair_capability"] == "figure-source-mapping"
