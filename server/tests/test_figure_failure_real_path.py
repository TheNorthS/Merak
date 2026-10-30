"""Pure regressions for complete deterministic failure scope and safe reuse."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services.deterministic_figure_builder import _current_entry_reusable, ensure_evaluation_design
from server.services.figure_producer_errors import DeterministicFigureProducerError, UnchangedDeterministicFigureDefect, aggregate_producer_failures
from server.services.scientific_asset_portfolio import mechanism_detail_reason
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.revision_gate_phases import build_current_gate
from server.workflows.revision_loop_context import RevisionLoopContext
from server.workflows.revision_loop_phases import prepare_consumer_state


def _context(root: Path, failure: Exception) -> RevisionLoopContext:
    host = WorkflowEngine()

    async def failed(*_args, **_kwargs):
        raise failure

    host._prepare_node_for_gate = failed
    node = WorkflowNode("figure", "Figure", "/paper-figure")
    run = WorkflowRun(id="failure-fixture", project_path=str(root), nodes=[node], status="running")
    context = RevisionLoopContext(host, node, run, "draft", "test", "balanced", {}, 3, 30, "", False, 2)
    context.result = ""
    context.unchanged_revision_event = None
    return context


@pytest.mark.asyncio
async def test_three_failures_keep_all_asset_targets_past_truncated_summary(tmp_path: Path) -> None:
    failures = [
        DeterministicFigureProducerError("layout collision " * 220).with_asset(identity, "deterministic_architecture")
        for identity in ("method_architecture", "core_mechanism")
    ]
    failures.append(DeterministicFigureProducerError("missing primary evaluation split").with_asset("evaluation_design", "deterministic_template"))
    error = aggregate_producer_failures(failures)
    context = _context(tmp_path, error)
    await prepare_consumer_state(context)
    await build_current_gate(context)
    assert len(context.gate["summary"]) == 2000
    diagnostics = context.host._gate_revision_diagnostics(context.gate)
    assert set(diagnostics["repair_scope"]["asset_ids"]) == {"method_architecture", "core_mechanism", "evaluation_design"}
    assert len(diagnostics["findings"]) == 3
    assert any("missing primary evaluation split" in item for item in diagnostics["issues"])
    assert all(item["owner_node"] == "figure" for item in diagnostics["findings"])
    assert "figures/diagrams/evaluation_design.svg" in diagnostics["repair_scope"]["target_files"]


def test_aggregate_keeps_unchanged_producer_stop_classification() -> None:
    errors = [UnchangedDeterministicFigureDefect("same failure").with_asset(identity, "deterministic_template") for identity in ("one", "two")]
    error = aggregate_producer_failures(errors)
    assert isinstance(error, UnchangedDeterministicFigureDefect)
    assert error.gate_details()["error_category"] == "figure_retry_deferred"
    assert len(error.findings) == 2


@pytest.mark.asyncio
async def test_unchanged_producer_gate_retains_stop_classification(tmp_path: Path) -> None:
    error = UnchangedDeterministicFigureDefect("same failed input").with_asset("method", "deterministic_architecture")
    context = _context(tmp_path, error)
    await prepare_consumer_state(context)
    await build_current_gate(context)
    assert context.gate["accepted"] is False
    assert context.gate["details"]["error_category"] == "figure_retry_deferred"
    assert context.gate["details"]["repair_scope"]["asset_ids"] == ["method"]


@pytest.mark.asyncio
async def test_unexpected_execution_fault_is_not_a_repairable_figure_finding(tmp_path: Path) -> None:
    context = _context(tmp_path, RuntimeError("unexpected execution failure"))
    with pytest.raises(RuntimeError, match="unexpected execution failure"):
        await prepare_consumer_state(context)


@pytest.mark.parametrize("strategy,target", [
    ("deterministic_architecture", "figures/diagrams/asset.json"),
    ("deterministic_template", "figures/diagrams/asset.svg"),
    ("deterministic_plot", "figures/plots/asset.py"),
])
def test_failure_scope_targets_each_actual_producer_source(strategy: str, target: str) -> None:
    error = DeterministicFigureProducerError("rejected producer fixture").with_asset("asset", strategy)
    assert error.gate_details()["repair_scope"]["target_files"] == [target, "figures/FIGURE_SPECS.json"]


@pytest.mark.asyncio
async def test_producer_collector_attributes_every_failure_without_model_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services import deterministic_figure_builder as builder

    async def fail(*_args, **_kwargs):
        raise ValueError("source producer failed")

    class Registry:
        def load(self, _path):
            return {"figures": []}

    monkeypatch.setattr(builder, "_ensure_deterministic_architectures", fail)
    monkeypatch.setattr(builder, "_ensure_deterministic_templates", fail)
    specs = [
        {"id": "method_architecture", "production_strategy": "deterministic_architecture"},
        {"id": "evaluation_design", "production_strategy": "deterministic_template"},
    ]
    with pytest.raises(DeterministicFigureProducerError) as raised:
        await ensure_evaluation_design(object(), object(), tmp_path, specs, {}, set(), Registry())
    assert [item["asset_ids"] for item in raised.value.findings] == [["method_architecture"], ["evaluation_design"]]


def test_source_byte_change_prevents_unchanged_input_reuse(tmp_path: Path) -> None:
    source = tmp_path / "experiments/src/train.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    output = tmp_path / "figure.pdf"
    output.write_bytes(b"existing-fixture-output")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    entry = {
        "source_path": "figure.pdf", "output_path": "figure.pdf",
        "source_sha256": sha(output), "output_sha256": sha(output),
        "metadata": {"producer_input_sha256": "same-input", "producer_kind": "deterministic",
                     "source_data": ["experiments/src/train.py"],
                     "source_bindings": [{"path": "experiments/src/train.py", "sha256": sha(source)}]},
    }
    assert _current_entry_reusable(entry, tmp_path, "same-input")
    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert not _current_entry_reusable(entry, tmp_path, "same-input")


def test_containment_overview_does_not_create_duplicate_detail_but_explicit_mandate_remains() -> None:
    objects = [{"id": "method", "kind": "operation"}, *[{"id": f"m{i}", "kind": "operation"} for i in range(4)]]
    scene = {"objects": objects, "relations": [{"from": "method", "to": f"m{i}", "kind": "containment"} for i in range(4)]}
    layout = {"split_required": True, "split_reasons": ["primary_branch_budget"]}
    assert mechanism_detail_reason({}, {}, [{"id": "M1"}], scene, layout) == ""
    assert mechanism_detail_reason({}, {"required_figure_assets": ["core_mechanism"]}, [{"id": "M1"}], scene, layout) == "explicit_contract"


def test_planned_method_uses_only_named_owner_comparators(tmp_path: Path) -> None:
    from server.tests.test_planned_method_contract import _write_idea
    from server.services.method_contract_planning import planned_method_contract

    _write_idea(tmp_path)
    path = tmp_path / "ideas/SELECTED_IDEA.json"
    idea = json.loads(path.read_text(encoding="utf-8"))
    idea["publication"]["comparator_names"] = ["Frozen method", "Matched reference"]
    path.write_text(json.dumps(idea), encoding="utf-8")
    planned = planned_method_contract(tmp_path, Path("ideas/SELECTED_IDEA.json"))
    assert planned["evaluation_contract"]["comparators_or_controls"] == ["Frozen method", "Matched reference"]
