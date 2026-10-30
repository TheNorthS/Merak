"""Source-only regressions distilled from run 109; generated code is never imported."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from server.services.evaluation_protocol_projection import project_evaluation_protocol
from server.services.experiment_implementation import experiment_implementation_service
from server.services.implementation_graph import reachable_graph
from server.services.implementation_model_bindings import has_bound_model_forward
from server.workflows.revision_progress_diagnostics import measure_revision_progress


@pytest.mark.parametrize("primary", ["montage", "All registered leave-one-montage-out domains"])
def test_109_primary_scope_preserved_without_caption_comparison(primary):
    evaluation = {"protocol_schema": 1, "holdout_axes": ["montage"], "primary_split": primary,
                  "primary_metric": "balanced_accuracy"}
    spec = {"evaluation": evaluation}
    config = {"evaluation": copy.deepcopy(evaluation), "data": {"active_holdout_axis": "montage"}}
    before = copy.deepcopy((spec, config))
    result = project_evaluation_protocol(spec, config)
    assert result["primary_split"] == primary
    assert (spec, config) == before
    config["evaluation"]["primary_split"] = "a different scientific scope"
    with pytest.raises(ValueError, match="declarations conflict"):
        project_evaluation_protocol(spec, config)


def test_109_named_split_manifest_is_compared_and_source_bound():
    spec = {"evaluation": {"holdout_axes": ["montage"]}, "data_requirements": {
        "manifest_paths": ["data/records.json", "data/split.json"],
        "split_manifests": {"montage": "data/split.json"}}}
    result = project_evaluation_protocol(spec)
    split = result["declared_splits"][0]
    assert split["manifest_path"] == "data/split.json"
    assert split["manifest_source_symbol"] == "data_requirements.split_manifests.montage"
    config = {"data": {"split_manifests": {"montage": "data/other.json"}}}
    with pytest.raises(ValueError, match="conflicting split manifest"):
        project_evaluation_protocol(spec, config)


@pytest.mark.parametrize("binding", ["from data import cmc_collate", "import data"])
def test_dataloader_callback_is_reachable_but_plain_reference_is_not(tmp_path, binding):
    main, data = tmp_path / "train.py", tmp_path / "data.py"
    callback = "cmc_collate" if binding.startswith("from") else "data.cmc_collate"
    trees = {main: ast.parse(f"{binding}\ndef main():\n    return DataLoader(records, collate_fn={callback})"),
             data: ast.parse("def cmc_collate(rows):\n    return list(zip(*rows))")}
    calls, _ = reachable_graph(trees, main)
    assert "cmc_collate" in calls
    trees[main] = ast.parse(f"{binding}\ndef main():\n    print({callback})")
    assert "cmc_collate" not in reachable_graph(trees, main)[0]


def test_shadowed_callback_import_does_not_reach_real_implementation(tmp_path):
    main, data = tmp_path / "train.py", tmp_path / "data.py"
    trees = {main: ast.parse("from data import cmc_collate\ndef main(cmc_collate):\n    return DataLoader(records, collate_fn=cmc_collate)"),
             data: ast.parse("def cmc_collate(rows):\n    return list(zip(*rows))")}
    _, reached = reachable_graph(trees, main)
    assert trees[data].body[0] not in reached


@pytest.mark.parametrize("variable", ["model", "student", "encoder"])
@pytest.mark.parametrize("style", ["annotation", "constructor"])
def test_source_bound_model_forward_does_not_depend_on_variable_name(tmp_path, variable, style):
    main, model = tmp_path / "train.py", tmp_path / "models.py"
    header = f"def main({variable}: CMCModel):" if style == "annotation" else "def main():"
    setup = "" if style == "annotation" else f"    {variable} = CMCModel().to('cpu')\n"
    source = f"from models import CMCModel\n{header}\n{setup}    return {variable}.forward_pair(a, b)"
    trees = {main: ast.parse(source), model: ast.parse("class CMCModel:\n    def forward_pair(self, a, b):\n        return a + b")}
    assert has_bound_model_forward(trees, [trees[main].body[1]])
    trees[main] = ast.parse(source.replace(f"return {variable}.forward_pair(a, b)", "return None"))
    assert not has_bound_model_forward(trees, [trees[main].body[1]])


def _project(tmp_path, main_source, test_source, checks):
    src = tmp_path / "experiments/src"
    src.mkdir(parents=True)
    (src / "train.py").write_text(main_source, encoding="utf-8")
    (src / "test_pipeline.py").write_text(test_source, encoding="utf-8")
    (src.parent / "RUN_SPEC.json").write_text(json.dumps({
        "entrypoint": "experiments/src/train.py", "command": "python experiments/src/train.py",
        "bounded_integration_test_command": "python -m unittest experiments.src.test_pipeline",
    }), encoding="utf-8")
    (src.parent / "METHOD_CONTRACT.json").write_text(json.dumps({
        "schema": 2, "status": "implemented", "implementation_level": "executable_training_pipeline",
        "implementation_checks": checks,
    }), encoding="utf-8")
    return experiment_implementation_service.audit(tmp_path)


def test_module_qualified_unittest_is_supporting_evidence_never_scientific_capability(tmp_path):
    check = {"id": "BOUNDED_TEST", "evidence": [{"path": "experiments/src/test_pipeline.py",
            "symbols": ["test_pipeline.CMCIntegrationTest.test_forward"]}]}
    report = _project(tmp_path, "def main():\n    return 0\n", """
class CMCIntegrationTest:
    def test_forward(self):
        model = build_model()
        output = model.forward(data)
        self.assertEqual(output.shape, expected)
""", [check])
    coverage = report["implementation_checks"]["BOUNDED_TEST"]
    assert coverage["passed"] and coverage["evidence_kind"] == "supporting_test_static"
    assert not coverage["execution_verified"]
    assert not report["capabilities"]["model_forward"]


def test_empty_test_cannot_be_used_as_supporting_evidence(tmp_path):
    check = {"id": "BOUNDED_TEST", "evidence": [{"path": "experiments/src/test_pipeline.py",
             "symbols": ["test_pipeline.test_forward"]}]}
    report = _project(tmp_path, "def main():\n    return 0\n", "def test_forward():\n    print('assertion')\n", [check])
    assert not report["implementation_checks"]["BOUNDED_TEST"]["passed"]


def test_early_preparation_failure_cannot_claim_old_findings_resolved():
    progress = measure_revision_progress(current={"PREPARATION"}, previous={"FORWARD", "CALLBACK"},
        scope_signature="after", previous_scope_signature="before", previous_count=0,
        revision_started=True, transport_attempted=False, evaluation_complete=False)
    assert progress["resolved_finding_ids"] == []
    assert progress["not_evaluated_finding_ids"] == ["CALLBACK", "FORWARD"]
    assert progress["consecutive_no_progress"] == 1


def test_new_errors_without_resolution_do_not_reset_no_progress_budget():
    progress = measure_revision_progress(current={"OLD", "NEW"}, previous={"OLD"},
        scope_signature="after", previous_scope_signature="before", previous_count=1,
        revision_started=True, transport_attempted=False)
    assert progress["consecutive_no_progress"] == 2
    assert progress["resolved_finding_ids"] == []
