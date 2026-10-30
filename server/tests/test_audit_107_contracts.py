"""Regression checks for false acceptance, revoked credentials and durable I/O."""
import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from server.services.experiment_implementation import experiment_implementation_service
from server.services import integration_environment
from server.services.settings_models import ModelConfig
from server.services.workflow_event_journal import WorkflowEventJournal
from server.tests.test_experiment_implementation import _implemented_contract, _write_full_pipeline, _write_json


def test_variable_names_cannot_claim_evaluation_or_persistence():
    source = "def main():\n    checkpoint = {}\n    metric = 'accuracy'\n    return checkpoint\n"
    capabilities = experiment_implementation_service._source_capabilities(source)
    assert capabilities["evaluation"] is False
    assert capabilities["persistence"] is False


def test_real_csv_and_numpy_load_calls_remain_valid_data_evidence():
    for source in ["rows = csv.DictReader(handle)", "signals = np.load(path)", "bundle = load_configured_data(config)"]:
        assert experiment_implementation_service._source_capabilities(source)["data_loading"] is True


@pytest.mark.parametrize("node", ["exp-design", "exp-run", "paper"])
def test_revision_fingerprint_tracks_new_validator_dependencies(node):
    from server.workflows.engine_revision_signature import _validator_source_paths
    names = {path.name for path in _validator_source_paths(node)}
    assert {"implementation_capabilities.py", "implementation_audit.py", "publication_labels.py",
            "simulation_table_publication.py", "table_panel_reference_contract.py"} <= names


def test_partial_runtime_wiring_and_same_name_other_module_cannot_pass(tmp_path):
    _write_full_pipeline(tmp_path)
    (tmp_path / "experiments/src/detached.py").write_text("def train():\n    result = 1\n    return result\n", encoding="utf-8")
    contract = _implemented_contract()
    contract["implementation_checks"][0]["evidence"].append({"path": "experiments/src/detached.py", "symbols": ["train"]})
    _write_json(tmp_path / "experiments/METHOD_CONTRACT.json", contract)
    report = experiment_implementation_service.audit(tmp_path)
    assert report["verdict"] == "FAIL"
    assert report["implementation_checks"]["I1"]["missing_symbols"] == ["train"]


def test_uncalled_training_helper_beside_main_cannot_supply_capabilities(tmp_path):
    _write_full_pipeline(tmp_path)
    path = tmp_path / "experiments/src/train.py"
    path.write_text(path.read_text(encoding="utf-8").replace("    train()", "    print('not wired')"), encoding="utf-8")
    _write_json(tmp_path / "experiments/METHOD_CONTRACT.json", _implemented_contract())
    report = experiment_implementation_service.audit(tmp_path)
    assert report["verdict"] == "FAIL"
    assert report["capabilities"]["optimization"] is False
    assert report["capabilities"]["persistence"] is False


def test_clearing_user_environment_override_revokes_it_without_erasing_system_value(monkeypatch):
    monkeypatch.setattr(integration_environment, "_owned", {})
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setenv("ZOTERO_API_KEY", "system-fixture")
    integration_environment.apply_integration_environment(ModelConfig(exa_api_key="fixture", zotero_api_key="override"))
    integration_environment.apply_integration_environment(ModelConfig())
    assert "EXA_API_KEY" not in os.environ
    assert os.environ["ZOTERO_API_KEY"] == "system-fixture"


@pytest.mark.asyncio
async def test_ordered_journal_io_does_not_block_event_loop(tmp_path, monkeypatch):
    journal = WorkflowEventJournal()
    original = journal.record
    write_completions = []
    def slow_record(*args):
        time.sleep(0.03)
        original(*args)
        write_completions.append(time.monotonic())
    monkeypatch.setattr(journal, "record", slow_record)
    ticks = []
    async def tick():
        for _ in range(10):
            await asyncio.sleep(0.005)
            ticks.append(time.monotonic())
    await asyncio.gather(tick(), *(journal.record_async(tmp_path, "fixture", "event", {"index": n}) for n in range(3)))
    await journal.close()
    lines = (tmp_path / ".merak/runs/fixture.events.jsonl").read_text().splitlines()
    assert [json.loads(line)["data"]["index"] for line in lines] == [0, 1, 2]
    assert len(ticks) == 10 and ticks[0] < write_completions[0]
