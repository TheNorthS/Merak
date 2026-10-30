"""Detail captions describe their projected science, never absent overview scope."""

import copy

import pytest

from server.services.figure_semantic_projection import project_figure_semantics
from server.services.scientific_asset_builders import design_assets
from server.services.scientific_scene_figure import compile_scientific_scene_figure


def _context(domain):
    if domain == "signal":
        method = "Shared signal objective"
        labels = ["Observed signal", "Overlapping channel subsets", "Paired spectral views",
            "Shared temporal encoder", "Shared and private factors", "Shared-only paired agreement",
            "Shared-private covariance penalty", "Frozen affine readout", "Dataset-held-out guardrail"]
    else:
        method = "Specimen response model"
        labels = ["Observed specimen", "Exposure allocation", "Paired molecular views",
            "Shared response transform", "Shared and private response factors", "Shared-only paired response",
            "Shared-private response covariance", "Reported response output", "External-cohort guardrail"]
    kinds = ["input", "operation", "operation", "operation", "operation", "operation", "operation", "output", "operation"]
    identities = ["observed", "subsets", "views", "encoder", "factors", "agreement", "covariance", "readout", "guardrail"]
    scene = {"schema": 1, "objects": [{"id": identity, "kind": kind, "label": label,
        "source_path": "experiments/EXPERIMENT_PLAN.md", "source_reference": f"Registered specification/{index}"}
        for index, (identity, kind, label) in enumerate(zip(identities, kinds, labels))],
        "relations": [*[{"from": source, "to": target, "kind": "data"} for source, target in (
            ("observed", "subsets"), ("subsets", "views"), ("views", "encoder"), ("encoder", "factors"),
            ("factors", "agreement"), ("factors", "covariance"), ("factors", "readout"))],
            {"from": "guardrail", "to": "observed", "kind": "constraint"},
            {"from": "guardrail", "to": "readout", "kind": "constraint"}]}
    mechanisms = [{"id": f"M{index}", "name": label, "description": "Registered scientific operation"}
                  for index, label in enumerate([*labels[1:3], labels[4], labels[8]], 1)]
    return {"title": method, "hypothesis": "The registered interaction changes the declared endpoint",
        "claims": [{"id": "C1"}], "mechanisms": mechanisms,
        "method_contract": {"schema": 2, "status": "implemented", "scientific_scene": scene,
            "evaluation_contract": {"comparators_or_controls": ["Registered response control"],
                "primary_outcomes": ["Reported response"]}},
        "source_artifacts": ["ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md"],
        "publication": {"language": "en", "method_name": method, "contribution_type": "objective_mechanism",
            "required_figures": ["core_mechanism"]},
        "run_spec": {"scientific_outputs": {"primary_split": "external_test"}}, "config": {}}


@pytest.mark.parametrize("domain", ["signal", "specimen"])
def test_detail_caption_matches_compiled_projection_and_keeps_overview_context_separate(domain):
    context = _context(domain)
    before = copy.deepcopy(context)
    assets = design_assets(context, {"schema": 1}, True)
    detail = next(asset for asset in assets if asset["narrative_level"] == "mechanism_detail")
    overview = next(asset for asset in assets if asset["narrative_level"] == "method_overview")
    projection = project_figure_semantics(detail)
    projected = projection["entities_states_transformations"]
    compiled = compile_scientific_scene_figure(detail)
    assert {node["id"] for node in compiled.spec["nodes"]} == {node["id"] for node in projected}
    assert {edge["from"] for edge in projection["relations"]}.issubset({node["id"] for node in projected})
    assert all(node["label"] in detail["caption"] for node in projected)
    assert context["method_contract"]["scientific_scene"]["objects"][-1]["label"] not in detail["caption"]
    assert context["method_contract"]["scientific_scene"]["objects"][-2]["label"] not in detail["caption"]
    assert context["method_contract"]["scientific_scene"]["objects"][-1]["label"] in {
        node["label"] for node in project_figure_semantics(overview)["entities_states_transformations"]}
    assert detail["scientific_scene"] == overview["scientific_scene"] == before["method_contract"]["scientific_scene"]
    assert overview["caption"] != detail["caption"]
    assert context == before


def test_caption_relation_text_is_retained_only_when_relation_survives_detail_projection():
    context = _context("signal")
    context["method_contract"]["scientific_scene"]["relations"][4]["label"] = "Shared-only pairing"
    context["method_contract"]["scientific_scene"]["relations"][-1]["label"] = "Held-out exclusion"
    detail = next(asset for asset in design_assets(context, {"schema": 1}, True)
                  if asset["narrative_level"] == "mechanism_detail")
    assert "Shared-only pairing" in detail["caption"]
    assert "Held-out exclusion" not in detail["caption"]
