from __future__ import annotations

import json
from pathlib import Path

from server.services.experiment_implementation import (
    experiment_implementation_service,
)
from server.services.method_contract import method_contract_service
from server.services.node_risk_audit import node_risk_audit_service


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _implemented_contract(*, check_symbol: str = "Model") -> dict:
    return {
                "schema": 2,
        "status": "implemented",
        "selected_idea": "Reachable Method",
        "evaluation_contract": {
            "primary_outcomes": ["accuracy", "AUROC", "calibration ECE"],
        },
        "implementation_checks": [
            {
                "id": "I1",
                "description": "Reachable accepted mechanism",
                "evidence": [
                    {
                        "path": "experiments/src/train.py",
                        "symbols": [check_symbol],
                    }
                ],
            }
        ],
    }


def _write_full_pipeline(root: Path, *, include_head: bool = True) -> None:
    head = """
class ClassifierHead:
    def forward(self, embeddings):
        return embeddings
""" if include_head else ""
    head_setup = "head = ClassifierHead()" if include_head else "head = model"
    _write_json(
        root / "experiments" / "RUN_SPEC.json",
        {
            "status": "ready",
            "entrypoint": "experiments/src/train.py",
            "command": "python experiments/src/train.py",
            "execution_mode": "train_and_evaluate",
        },
    )
    source = f"""
import json

class Model:
    def forward(self, batch):
        return batch

{head}

def load_data():
    return DataLoader(ConfiguredDataset())

def predict(model, batch):
    return model.forward(batch)

def train():
    model = Model()
    {head_setup}
    optimizer = Adam(model.parameters())
    for batch in load_data():
        embeddings = model.forward(batch)
        predictions = head.forward(embeddings)
        loss = cross_entropy(predictions, batch.targets)
        loss.backward()
        optimizer.step()
    model.eval()
    predictions = predict(head, batch)
    metrics = {{"accuracy": accuracy(predictions, batch.targets)}}
    with open("metrics.json", "w") as stream:
        json.dump(metrics, stream)
    return metrics

def main():
    train()

if __name__ == "__main__":
    main()
"""
    path = root / "experiments" / "src" / "train.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_static_code_check_cannot_claim_implemented(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        _implemented_contract(check_symbol="validate_static_contract"),
    )
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "status": "planned_code_check_only",
            "entrypoint": "experiments/src/train.py",
            "static_check_command": "python experiments/src/train.py",
            "execution_prohibited_in_this_stage": True,
        },
    )
    train = tmp_path / "experiments" / "src" / "train.py"
    train.parent.mkdir(parents=True)
    train.write_text(
        "def validate_static_contract():\n"
        "    return {'valid': True}\n\n"
        "def main():\n"
        "    validate_static_contract()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "FAIL"
    ids = {item["id"] for item in report["findings"]}
    assert "IMPL-STATUS-001" in ids
    assert "IMPL-FLOW-OPTIMIZATION" in ids
    assert "IMPL-MECH-I1-UNREACHABLE" in ids


def test_complete_reachable_training_pipeline_passes(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        _implemented_contract(),
    )
    _write_full_pipeline(tmp_path)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS", report["findings"]
    assert all(report["capabilities"].values())
    assert report["implementation_checks"]["I1"]["passed"] is True


def test_separate_evaluation_entrypoint_counts_as_reachable(tmp_path: Path) -> None:
    contract = _implemented_contract()
    contract["implementation_checks"].append({
        "id": "I2",
        "description": "Registered evaluation path",
        "evidence": [{
            "path": "experiments/src/evaluation.py",
            "symbols": ["evaluate"],
        }],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    _write_full_pipeline(tmp_path)
    evaluation = tmp_path / "experiments" / "src" / "evaluation.py"
    evaluation.write_text(
        "def evaluate():\n"
        "    values = [1, 2]\n"
        "    return sum(values)\n\n"
        "def main():\n"
        "    evaluate()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec["evaluation_command"] = "python experiments/src/evaluation.py"
    _write_json(run_spec_path, run_spec)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS", report["findings"]
    assert report["implementation_checks"]["I2"]["passed"] is True
    assert "experiments/src/evaluation.py" in report["entrypoints"]


def test_same_named_run_functions_are_resolved_per_module(tmp_path: Path) -> None:
    contract = _implemented_contract()
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    src = tmp_path / "experiments" / "src"
    src.mkdir(parents=True)
    _write_json(tmp_path / "experiments" / "RUN_SPEC.json", {
        "entrypoint": "experiments/src/train.py",
        "execution_command": "python experiments/src/train.py",
    })
    (src / "evaluation.py").write_text(
        "def run():\n    return {'accuracy': 1.0}\n", encoding="utf-8"
    )
    (src / "train.py").write_text(
        "from evaluation import run as evaluate_run\n"
        "def run():\n"
        "    for batch in [1, 2]:\n"
        "        loss = batch\n"
        "        loss.backward()\n"
        "        optimizer.step()\n"
        "    return evaluate_run()\n"
        "if __name__ == '__main__':\n    run()\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert "experiments/src/train.py" in report["entrypoints"]
    assert report["capabilities"]["optimization"] is True


def test_unittest_discovery_entrypoint_counts_test_method_as_reachable(
    tmp_path: Path,
) -> None:
    contract = _implemented_contract()
    contract["implementation_checks"].append({
        "id": "I2",
        "description": "Bounded integration route",
        "evidence": [{
            "path": "experiments/src/test_pipeline.py",
            "symbols": ["PipelineTest.test_reachable_route"],
        }],
    })
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    _write_full_pipeline(tmp_path)
    integration_test = tmp_path / "experiments" / "src" / "test_pipeline.py"
    integration_test.write_text(
        "import unittest\n\n"
        "class PipelineTest(unittest.TestCase):\n"
        "    def test_reachable_route(self):\n"
        "        values = [1, 2, 3]\n"
        "        self.assertEqual(sum(values), 6)\n",
        encoding="utf-8",
    )
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec["bounded_integration_test_command"] = (
        "python -m unittest discover -s experiments/src -p test_pipeline.py -v"
    )
    run_spec["integration_contract"] = {
        "bounded_test": "experiments/src/test_pipeline.py",
    }
    _write_json(run_spec_path, run_spec)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS", report["findings"]
    assert report["implementation_checks"]["I2"]["passed"] is True
    assert "experiments/src/test_pipeline.py" in report["entrypoints"]


def test_implemented_pipeline_may_remain_not_executed_during_design(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        _implemented_contract(),
    )
    _write_full_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec.update({
        "status": "frozen_not_executed",
        "execution_mode": "code_check_only_current_session",
        "execution_status": "not_executed",
        "execution_prohibited_in_this_stage": True,
        "static_check_command": "python -m py_compile experiments/src/train.py",
    })
    _write_json(run_spec_path, run_spec)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS", report["findings"]
    assert not any(
        item["id"] == "IMPL-STATUS-001" for item in report["findings"]
    )


def test_implemented_contract_rejects_self_declared_unreachable_steps(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        {
            **_implemented_contract(),
            "implementation_level": (
                "training_entrypoint_with_unreachable_final_evaluation_path"
            ),
        },
    )
    _write_full_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec.update({
        "implementation_readiness": (
            "integration_blocked_unreachable_final_mechanisms"
        ),
        "execution_status": "not_executed",
        "execution_prohibited_in_this_stage": True,
        "blocked_required_steps": [
            "calibration_and_final_evaluation",
            "efficiency_repeats",
            "registered_analysis",
        ],
    })
    _write_json(run_spec_path, run_spec)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "FAIL"
    finding = next(
        item for item in report["findings"]
        if item["id"] == "IMPL-STATUS-002"
    )
    assert "experiments/src/train.py" in finding["target_files"]


def test_not_executed_state_is_not_an_implementation_blocker(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        {
            **_implemented_contract(),
            "implementation_level": "executable_experiment_pipeline",
        },
    )
    _write_full_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec.update({
        "implementation_readiness": "implemented",
        "execution_status": "not_executed",
        "execution_prohibited_in_this_stage": True,
    })
    _write_json(run_spec_path, run_spec)

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS", report["findings"]
    assert not any(
        item["id"] == "IMPL-STATUS-002" for item in report["findings"]
    )


def test_named_mechanism_must_be_reachable_from_entrypoint(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        _implemented_contract(check_symbol="orphan_mechanism"),
    )
    _write_full_pipeline(tmp_path)
    train = tmp_path / "experiments" / "src" / "train.py"
    train.write_text(
        train.read_text(encoding="utf-8")
        + "\ndef orphan_mechanism(value):\n    return value * 2\n",
        encoding="utf-8",
    )

    report = experiment_implementation_service.audit(tmp_path)

    assert any(
        item["id"] == "IMPL-MECH-I1-UNREACHABLE"
        for item in report["findings"]
    )


def test_planned_design_does_not_claim_executable_implementation(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        {"schema": 2, "status": "planned"},
    )

    report = experiment_implementation_service.audit(tmp_path)

    assert report["verdict"] == "PASS"
    assert report["claimed_implemented"] is False


def test_enabled_probe_with_null_heads_blocks_implemented_claim(tmp_path: Path) -> None:
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", _implemented_contract())
    _write_full_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec["command"] += " --config experiments/configs/main.yaml"
    _write_json(run_spec_path, run_spec)
    config_path = tmp_path / "experiments" / "configs" / "main.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "model:\n  subject_classes: null\n  session_classes: null\n"
        "objective:\n  subject_probe_weight: 0.0\n  session_probe_weight: 0.0\n"
        "ablations:\n  subject_session_probe:\n    enabled: true\n    mode: joint_objective\n",
        encoding="utf-8",
    )

    report = experiment_implementation_service.audit(tmp_path)

    finding = next(item for item in report["findings"] if item["id"] == "IMPL-CONFIG-PROBE-SUBJECT-SESSION-PROBE")
    assert report["blocking"] is True
    assert "model.subject_classes=None" in finding["message"]
    assert "model.session_classes=None" in finding["message"]
    assert "experiments/configs/main.yaml" in finding["target_files"]
    assert report["probe_configuration"] == [{
        "name": "subject_session_probe",
        "mechanism_id": "",
        "source_path": "experiments/configs/main.yaml",
        "training_mode": "joint_objective",
        "head_status": "unconfigured",
        "configured_heads": [],
        "missing_heads": ["model.subject_classes=None", "model.session_classes=None"],
        "joint_objective_status": "inactive",
        "objective_weights": {
            "objective.subject_probe_weight": 0.0,
            "objective.session_probe_weight": 0.0,
        },
    }]
    exp_design = node_risk_audit_service.audit_node(
        tmp_path,
        "exp-design",
        {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"},
        persist=False,
    )
    assert any(
        item["id"] == "IMPL-CONFIG-PROBE-SUBJECT-SESSION-PROBE" and item["severity"] == "warning"
        for item in exp_design["findings"]
    )
    physical_design = node_risk_audit_service.audit_node(
        tmp_path, "exp-design", {"run_experiment": True}, persist=False,
    )
    assert any(
        item["id"] == "IMPL-CONFIG-PROBE-SUBJECT-SESSION-PROBE" and item["severity"] == "blocker"
        for item in physical_design["findings"]
    )


def test_probe_config_gate_preserves_planned_and_dynamic_designs(tmp_path: Path) -> None:
    contract = _implemented_contract()
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    _write_full_pipeline(tmp_path)
    config_path = tmp_path / "experiments" / "configs" / "main.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "model:\n  subject_classes: null\n"
        "ablations:\n  subject_probe:\n    enabled: false\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert not any(item["id"].startswith("IMPL-CONFIG-PROBE-") for item in report["findings"])

    config_path.write_text(
        "model:\n  subject_classes: null\n"
        "ablations:\n  subject_probe:\n    enabled: true\n",
        encoding="utf-8",
    )
    contract["status"] = "planned"
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    report = experiment_implementation_service.audit(tmp_path)
    assert not any(item["id"].startswith("IMPL-CONFIG-PROBE-") for item in report["findings"])

    config_path.write_text(
        "model:\n  subject_classes: null\n  session_classes: null\n"
        "objective:\n  subject_probe_weight: 0.0\n  session_probe_weight: 0.0\n"
        "ablations:\n  subject_session_probe:\n    enabled: true\n    mode: frozen_downstream\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert report["probe_configuration"][0]["training_mode"] == "frozen_downstream"
    assert report["probe_configuration"][0]["head_status"] == "not_required"
    assert not any(item["id"].startswith("IMPL-CONFIG-PROBE-") for item in report["findings"])

    config_path.write_text(
        "model:\n  subject_classes: null\n  session_classes: null\n"
        "objective:\n  subject_probe_weight: 0.0\n  session_probe_weight: 0.0\n"
        "ablations:\n  subject_session_probe:\n    enabled: true\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert report["probe_configuration"][0]["training_mode"] == "unspecified"
    assert report["probe_configuration"][0]["head_status"] == "unverified_mode"
    assert not any(item["id"].startswith("IMPL-CONFIG-PROBE-") for item in report["findings"])

    config_path.write_text(
        "model:\n  subject_classes: null\n"
        "objective:\n  subject_probe_weight: 0.5\n"
        "ablations:\n  subject_probe:\n    enabled: true\n",
        encoding="utf-8",
    )
    contract["status"] = "implemented"
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    report = experiment_implementation_service.audit(tmp_path)
    assert report["probe_configuration"][0]["training_mode"] == "joint_objective"
    assert any(item["id"] == "IMPL-CONFIG-PROBE-SUBJECT-PROBE" for item in report["findings"])

    contract["status"] = "implemented"
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", contract)
    config_path.write_text(
        "model:\n  subject_classes: auto\n"
        "ablations:\n  subject_probe:\n    enabled: true\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert not any(item["id"].startswith("IMPL-CONFIG-PROBE-") for item in report["findings"])


def test_predictive_metrics_require_reachable_task_head(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        _implemented_contract(),
    )
    _write_full_pipeline(tmp_path, include_head=False)

    report = experiment_implementation_service.audit(tmp_path)

    assert any(
        item["id"] == "IMPL-INFERENCE-001"
        for item in report["findings"]
    )


def test_synthetic_preview_does_not_accept_planned_method_contract(
    tmp_path: Path,
) -> None:
    ideas = tmp_path / "ideas"
    experiments = tmp_path / "experiments"
    ideas.mkdir()
    experiments.mkdir()
    _write_json(
        ideas / "SELECTED_IDEA.json",
        {
            "schema": 2,
            "status": "accepted",
            "title": "Reachable Method",
            "problem_statement": "A falsifiable study.",
            "hypothesis": "The mechanism changes accuracy.",
                "claims": [{"id": "C1", "statement": "Accuracy changes.", "publication_statement": "Accuracy changes."}],
            "mechanisms": [
                    {"id": "M1", "name": "Mechanism", "description": "Operation.", "publication_name": "Mechanism", "publication_description": "Named operation.", "publication_evaluation": "Matched comparison."}
            ],
                "falsification_conditions": ["No change under matched controls."],
                "publication": {"language": "en", "title": "Reachable Method", "method_name": "Reachable method", "contribution_type": "objective_mechanism", "comparator_names": ["Reachable method", "Matched baseline"]},
        },
    )
    (ideas / "novelty_report.md").write_text(
        "# Novelty\n\nReachable Method\n", encoding="utf-8"
    )
    (experiments / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nReachable Method\n", encoding="utf-8"
    )
    assert method_contract_service.ensure_planned_method_contract(tmp_path)

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "exp-design",
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
        persist=False,
    )

    assert report["blocking"] is True
    assert any(
        "status must be implemented" in str(item.get("message"))
        for item in report["findings"]
    )
