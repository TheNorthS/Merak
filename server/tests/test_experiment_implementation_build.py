from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

import pytest

import server.agent.tools as agent_tools
from server.services.experiment_implementation_build import (
    ML_STAGES,
    experiment_implementation_build_service,
)
from server.services.method_contract import method_contract_service
from server.workflows.engine import WorkflowEngine, WorkflowRun


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write(path, json.dumps(payload, indent=2))


def _seed_contracts(root: Path) -> None:
    _write_json(
        root / "ideas" / "SELECTED_IDEA.json",
        {
            "schema": 2,
            "status": "accepted",
            "title": "Reachable Classification Method",
            "problem_statement": "Test a mechanism under isolated groups.",
            "hypothesis": "The mechanism improves accuracy.",
            "claims": [{"id": "C1", "statement": "Accuracy improves.", "publication_statement": "Accuracy improves."}],
            "mechanisms": [
                {
                    "id": "M1",
                    "name": "Accepted mechanism",
                    "description": "Transforms representations.",
                    "publication_name": "Representation transformation",
                    "publication_description": "Transforms representations under the declared comparison.",
                    "publication_evaluation": "Matched accuracy comparison.",
                    "required": True,
                }
            ],
            "falsification_conditions": ["No improvement under matched controls."],
            "publication": {"language": "en", "title": "Reachable Classification Method", "method_name": "Reachable classifier", "contribution_type": "model_architecture", "comparator_names": ["Reachable classifier", "Matched baseline"]},
        },
    )
    _write(
        root / "experiments" / "EXPERIMENT_PLAN.md",
        "# Experiment Plan\n\nReachable Classification Method\n",
    )


def _write_complete_pipeline(root: Path) -> None:
    _write(
        root / "experiments" / "src" / "data.py",
        "class ConfiguredDataset:\n"
        "    pass\n\n"
        "def grouped_split(records):\n"
        "    return records, records, records\n\n"
        "def load_data():\n"
        "    dataset = ConfiguredDataset()\n"
        "    train, validation, test = grouped_split(dataset)\n"
        "    return DataLoader(train)\n",
    )
    _write(
        root / "experiments" / "src" / "data_contract.py",
        "def leakage_audit(train_ids, validation_ids, test_ids):\n"
        "    return not (set(train_ids) & set(test_ids))\n",
    )
    _write(
        root / "experiments" / "src" / "models.py",
        "def accepted_mechanism(value):\n"
        "    return value\n\n"
        "class ClassificationHead:\n"
        "    def forward(self, embeddings):\n"
        "        return embeddings\n\n"
        "class Model:\n"
        "    def __init__(self):\n"
        "        self.task_head = ClassificationHead()\n\n"
        "    def forward(self, batch):\n"
        "        embeddings = accepted_mechanism(batch)\n"
        "        return self.task_head.forward(embeddings)\n\n"
        "    def parameters(self):\n"
        "        return []\n\n"
        "    def eval(self):\n"
        "        return self\n",
    )
    _write(
        root / "experiments" / "src" / "objectives.py",
        "def classification_objective(logits, targets):\n"
        "    return cross_entropy(logits, targets)\n",
    )
    _write(
        root / "experiments" / "src" / "metrics.py",
        "def accuracy(predictions, targets):\n"
        "    return metric(predictions, targets)\n",
    )
    _write(
        root / "experiments" / "src" / "evaluation.py",
        "def evaluate(model, batch):\n"
        "    model.eval()\n"
        "    predictions = model.forward(batch)\n"
        "    return {'accuracy': accuracy(predictions, batch.targets)}\n",
    )
    _write(
        root / "experiments" / "src" / "provenance.py",
        "import json\n\n"
        "def persist_results(metrics):\n"
        "    with open('metrics.json', 'w') as stream:\n"
        "        json.dump({'metrics': metrics, 'provenance': 'bound'}, stream)\n",
    )
    _write(
        root / "experiments" / "src" / "train.py",
        "from data import load_data\n"
        "from evaluation import evaluate\n"
        "from models import Model\n"
        "from objectives import classification_objective\n"
        "from provenance import persist_results\n\n"
        "def train():\n"
        "    model = Model()\n"
        "    optimizer = Adam(model.parameters())\n"
        "    for batch in load_data():\n"
        "        logits = model.forward(batch)\n"
        "        loss = classification_objective(logits, batch.targets)\n"
        "        loss.backward()\n"
        "        optimizer.step()\n"
        "    metrics = evaluate(model, batch)\n"
        "    persist_results(metrics)\n"
        "    return metrics\n\n"
        "def main():\n"
        "    train()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
    )
    _write(
        root / "experiments" / "src" / "test_pipeline.py",
        "def test_pipeline_contract():\n"
        "    assert callable(train)\n",
    )
    _write_json(
        root / "experiments" / "RUN_SPEC.json",
        {
            "status": "ready",
            "execution_mode": "train_and_evaluate",
            "entrypoint": "experiments/src/train.py",
            "command": "python experiments/src/train.py",
            "repetitions": {"seeds": [13, 42, 73]},
        },
    )
    _write_json(
        root / "experiments" / "METHOD_CONTRACT.json",
        {
            "schema": 2,
            "status": "implemented",
            "implementation_level": "executable_training_pipeline",
            "selected_idea": "Reachable Classification Method",
            "idea_contract_path": "ideas/SELECTED_IDEA.json",
            "idea_contract_sha256": hashlib.sha256(
                (root / "ideas" / "SELECTED_IDEA.json").read_bytes()
            ).hexdigest(),
            "evaluation_contract": {
                "primary_outcomes": ["accuracy"],
                "comparators_or_controls": ["matched baseline"],
                "component_tests": ["M1 ablation"],
                "failure_conditions": ["no improvement"],
            },
            "implementation_checks": [
                {
                    "id": "I1",
                    "description": "Accepted mechanism is reachable",
                    "evidence": [
                        {
                            "path": "experiments/src/models.py",
                            "symbols": ["accepted_mechanism", "Model"],
                        }
                    ],
                }
            ],
            "mechanism_coverage": [{
                "idea_mechanism_id": "M1",
                "implementation_check_ids": ["I1"],
            }],
            "claim_evidence_plan": [{
                "idea_claim_id": "C1",
                "outcomes": ["accuracy"],
                "failure_conditions": ["no improvement"],
            }],
            "scientific_scene": {
                "schema": 1,
                "objects": [{
                    "id": "accepted_mechanism",
                    "kind": "operation",
                    "label": "Reachable accepted mechanism",
                    "source_path": "experiments/src/models.py",
                }],
                "relations": [],
            },
        },
    )
    _write_json(
        root / "experiments" / "IMPLEMENTATION_EVIDENCE_PATCH.json",
        {
            "schema": 1,
            "checks": [{
                "check_id": "I1",
                "description": "Accepted mechanism is reachable",
                "evidence": [{
                    "path": "experiments/src/models.py",
                    "symbols": ["accepted_mechanism", "Model"],
                }],
            }],
        },
    )

    _write(
        root / "experiments" / "configs" / "main.yaml",
        "model:\n  name: reachable_method\ntraining:\n  seeds: [1, 2, 3]\n",
    )


def test_method_contract_rejects_alternate_mechanism_key_without_rewriting(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mechanism_coverage"] = [
        {"id": "M1", "implementation_check_ids": ["I1"]}
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    valid, issues, _ = method_contract_service.validate_method_contract(
        tmp_path,
        "Reachable Classification Method",
    )
    assert valid is False
    assert any("unknown idea mechanism: [empty]" in issue for issue in issues)
    assert json.loads(path.read_text(encoding="utf-8"))["mechanism_coverage"] == [
        {"id": "M1", "implementation_check_ids": ["I1"]}
    ]


def test_blueprint_freezes_five_implementation_stages(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)

    blueprint = experiment_implementation_build_service.ensure_blueprint(
        tmp_path,
        "classification research",
    )

    assert blueprint["implementation_family"] == "machine_learning"
    assert [item["id"] for item in blueprint["stages"]] == [
        "data",
        "method",
        "training",
        "evaluation",
        "integration",
    ]
    assert blueprint["mechanisms"][0]["id"] == "M1"


def test_integration_rejects_noncanonical_method_contract(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["schema"] = 1
    contract.pop("implementation_checks")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any(
        "integration METHOD_CONTRACT: method contract uses an unsupported schema; "
        "current schema=2" in issue
        for issue in report["issues"]
    )
    assert any(
        "method contract must declare implementation_checks" in issue
        for issue in report["issues"]
    )


def test_integration_rejects_method_contract_that_drops_scientific_scene(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.pop("scientific_scene")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any(
        "integration METHOD_CONTRACT: scientific_scene must use schema=1" in issue
        for issue in report["issues"]
    )


def test_integration_rejects_run_spec_without_explicit_seed_list(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec.pop("repetitions")
    run_spec_path.write_text(json.dumps(run_spec), encoding="utf-8")

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any("RUN_SPEC must declare an explicit seed list" in issue for issue in report["issues"])


def test_integration_rejects_unresolved_scientific_command_placeholder(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec["command"] = (
        "python experiments/src/train.py --held-out "
        "<manifest_selected_subject_ids> --seed {seed}"
    )
    run_spec_path.write_text(json.dumps(run_spec), encoding="utf-8")

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any(
        "contains unresolved placeholder(s): <manifest_selected_subject_ids>"
        in issue
        for issue in report["issues"]
    )


def test_integration_reports_malformed_yaml_instead_of_raising(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    _write(
        tmp_path / "experiments" / "configs" / "main.yaml",
        "evaluation:\n  subject_probe_testability:\n"
        "    bare scalar without colon\n"
        "    held_out_behavior: not_testable\n",
    )

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any(
        "main.yaml is not valid structured config" in issue
        and "ScannerError" in issue
        for issue in report["issues"]
    )


def test_integration_reports_contract_and_yaml_findings_together(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["claim_evidence_plan"] = [{
        "claim_id": "C1",
        "alternative_explanations": ["capacity"],
    }]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    _write(
        tmp_path / "experiments" / "configs" / "main.yaml",
        "evaluation:\n  invalid_mapping:\n"
        "    bare scalar without colon\n"
        "    child: value\n",
    )

    report = experiment_implementation_build_service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )

    assert report["passed"] is False
    assert any("main.yaml is not valid structured config" in issue for issue in report["issues"])
    assert any("claim_evidence_plan[0] must declare outcomes" in issue for issue in report["issues"])
    assert any("claim_evidence_plan[0] must declare failure_conditions" in issue for issue in report["issues"])


def test_existing_build_is_atomically_revalidated_after_gate_fix(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    service = experiment_implementation_build_service
    direction = "classification research"
    service.ensure_blueprint(tmp_path, direction)

    for stage in ML_STAGES:
        report = service.validate_stage(tmp_path, stage.id, direction)
        assert report["passed"], report
        service.record_stage(
            tmp_path,
            stage.id,
            report,
            direction,
            attempts=1,
            session_summaries=[f"implemented {stage.id}"],
        )

    build_path = tmp_path / "experiments" / "IMPLEMENTATION_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["stages"]["integration"]["status"] = "needs_revision"
    build["stages"]["integration"]["issues"] = ["legacy missing symbol"]
    build["status"] = "in_progress"
    build["accepted_stages"] = ["data"]
    build["current_stage"] = "method"
    build_path.write_text(json.dumps(build), encoding="utf-8")

    result = service.revalidate_existing_build(tmp_path, direction)

    assert result["complete"] is True
    refreshed = service.load_build(tmp_path)
    assert refreshed["status"] == "complete"
    assert refreshed["accepted_stages"] == [stage.id for stage in ML_STAGES]
    assert refreshed["current_stage"] == ""
    assert all(
        refreshed["stages"][stage.id]["status"] == "accepted"
        for stage in ML_STAGES
    )
    assert refreshed["stages"]["method"]["session_summaries"] == [
        "implemented method"
    ]


def test_existing_build_revalidation_refuses_changed_accepted_output(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    service = experiment_implementation_build_service
    direction = "classification research"
    service.ensure_blueprint(tmp_path, direction)

    for stage in ML_STAGES:
        report = service.validate_stage(tmp_path, stage.id, direction)
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report, direction, attempts=1)

    model_path = tmp_path / "experiments" / "src" / "models.py"
    model_path.write_text(
        model_path.read_text(encoding="utf-8") + "\nMODEL_REVISION = 2\n",
        encoding="utf-8",
    )
    before = service.load_build(tmp_path)

    result = service.revalidate_existing_build(tmp_path, direction)

    assert result["complete"] is False
    assert any("accepted owned artifacts changed" in issue for issue in result["issues"])
    after = service.load_build(tmp_path)
    assert after["stages"]["method"]["status"] == "needs_revision"
    assert after["stages"]["method"]["output_sha256"] == before["stages"]["method"]["output_sha256"]
    assert after["status"] != "complete"


@pytest.mark.parametrize(
    ("title", "direction", "expected_family"),
    [
        ("Randomized intervention protocol", "clinical participant trial", "external_protocol"),
        ("Finite element convergence study", "numerical simulation modeling", "computational_general"),
        ("Theorem proof obligations", "formal theorem and counterexample", "formal_verification"),
    ],
)
def test_blueprint_maps_non_eeg_research_families_to_domain_contracts(
    tmp_path: Path,
    title: str,
    direction: str,
    expected_family: str,
) -> None:
    _seed_contracts(tmp_path)
    idea = json.loads(
        (tmp_path / "ideas" / "SELECTED_IDEA.json").read_text(encoding="utf-8")
    )
    idea["title"] = title
    idea["problem_statement"] = direction
    idea["hypothesis"] = "The prespecified analysis is informative."
    idea["claims"] = [{
        "id": "C1",
        "statement": "The prespecified analysis is informative.",
        "publication_statement": "The prespecified analysis is informative.",
    }]
    idea["mechanisms"] = [{
        "id": "M1",
        "name": "Prespecified procedure",
        "description": "Execute the domain-specific prespecified procedure.",
        "publication_name": "Prespecified procedure",
        "publication_description": "Executes the registered scientific procedure.",
        "publication_evaluation": "Compare the registered outcome with its matched reference.",
        "required": True,
    }]
    contribution = {
        "external_protocol": "experimental_protocol",
        "computational_general": "empirical_discovery",
        "formal_verification": "theory_proof",
    }[expected_family]
    idea["publication"] = {
        "language": "en",
        "title": title,
        "method_name": title,
        "contribution_type": contribution,
        "comparator_names": [title, "Matched reference"],
    }
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps(idea), encoding="utf-8"
    )

    service = experiment_implementation_build_service
    blueprint = service.ensure_blueprint(tmp_path, direction)

    assert blueprint["implementation_family"] == expected_family
    assert blueprint["research_family"]
    assert blueprint["study_archetype"]
    assert blueprint["domain_evidence_contract"]["provenance"]
    assert service.applicable(tmp_path, direction) is True


def test_stage_prompt_carries_field_evidence_requirements(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "Finite element numerical simulation")

    prompt = service.stage_prompt(tmp_path, "evaluation", "Finite element numerical simulation")

    assert "Domain evidence contract" in prompt
    assert "Provenance:" in prompt
    assert "Publication family:" in prompt
    assert "current schema=2" in prompt
    assert "Preserve its authored `scientific_scene`" in prompt


def test_stages_pass_only_after_complete_reachable_pipeline(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    experiment_implementation_build_service.ensure_blueprint(tmp_path)

    empty = experiment_implementation_build_service.audit(tmp_path)
    assert empty["blocking"] is True
    assert any("data stage produced no source" in issue for issue in empty["issues"])

    _write_complete_pipeline(tmp_path)
    for stage in ML_STAGES:
        stage_report = experiment_implementation_build_service.validate_stage(
            tmp_path,
            stage.id,
        )
        experiment_implementation_build_service.record_stage(
            tmp_path,
            stage.id,
            stage_report,
        )
    complete = experiment_implementation_build_service.audit(tmp_path)

    assert complete["blocking"] is False, complete["issues"]
    assert all(report["passed"] for report in complete["stages"])


def test_stage_records_are_reused_and_upstream_change_invalidates_downstream(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    experiment_implementation_build_service.ensure_blueprint(tmp_path)
    _write_complete_pipeline(tmp_path)
    service = experiment_implementation_build_service
    for stage in ML_STAGES:
        report = service.validate_stage(tmp_path, stage.id)
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report)

    assert all(service.can_reuse(tmp_path, stage.id) for stage in ML_STAGES)

    data_path = tmp_path / "experiments" / "src" / "data.py"
    data_path.write_text(
        data_path.read_text(encoding="utf-8") + "\nDATA_REVISION = 2\n",
        encoding="utf-8",
    )

    assert service.can_reuse(tmp_path, "data") is False
    assert service.can_reuse(tmp_path, "method") is False
    assert service.can_reuse(tmp_path, "training") is False


def test_plan_prose_change_invalidates_integration_not_accepted_source_stages(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path)
    _write_complete_pipeline(tmp_path)
    for stage in ML_STAGES:
        report = service.validate_stage(tmp_path, stage.id)
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report)
    plan = tmp_path / "experiments/EXPERIMENT_PLAN.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\nEditorial clarification.\n")

    assert service.can_reuse(tmp_path, "data") is True
    assert service.can_reuse(tmp_path, "method") is True
    assert service.can_reuse(tmp_path, "training") is True
    assert service.can_reuse(tmp_path, "evaluation") is True
    assert service.can_reuse(tmp_path, "integration") is False


def test_exp_design_primary_prompt_owns_blueprint_not_source_code(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    run = WorkflowRun(project_path=str(tmp_path))

    prompt = WorkflowEngine()._input_exp_design(
        "classification research",
        {},
        run,
    )

    assert "IMPLEMENTATION_BLUEPRINT.json" in prompt
    assert '"schema": 2' in prompt
    assert '"scientific_scene"' in prompt
    assert "当前主会话只冻结" in prompt
    assert "不生成 `experiments/src/` 源代码" in prompt
    assert "data → method → training → evaluation → integration" in prompt


@pytest.mark.asyncio
async def test_engine_executes_all_implementation_stages_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "classification research")
    _write_complete_pipeline(tmp_path)
    calls: list[str] = []

    async def fake_invoke_skill(_skill_name: str, arguments: str, **_kwargs) -> str:
        match = re.search(r"Stage:\s+(\w+)", arguments)
        assert match
        calls.append(match.group(1))
        return f"implemented {match.group(1)}"

    async def ignore_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_tools, "invoke_skill", fake_invoke_skill)
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.mark_execution",
        lambda *_args, **_kwargs: None,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", ignore_event)
    run = WorkflowRun(id="staged-build", project_path=str(tmp_path))

    report = await engine._execute_staged_experiment_implementation(
        run=run,
        direction="classification research",
        opts={"run_experiment": False},
    )

    assert report["blocking"] is False, report
    assert calls == [stage.id for stage in ML_STAGES]
    build = service.load_build(tmp_path)
    assert build["status"] == "complete"
    assert build["accepted_stages"] == calls


@pytest.mark.asyncio
async def test_previously_attempted_stage_revalidates_without_empty_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "classification research")
    _write_complete_pipeline(tmp_path)

    for stage in ML_STAGES[:-1]:
        report = service.validate_stage(tmp_path, stage.id, "classification research")
        assert report["passed"], report
        service.record_stage(
            tmp_path,
            stage.id,
            report,
            "classification research",
        )

    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = run_spec_path.read_text(encoding="utf-8")
    run_spec_path.unlink()
    failed = service.validate_stage(
        tmp_path,
        "integration",
        "classification research",
    )
    assert failed["passed"] is False
    run_spec_path.write_text(run_spec, encoding="utf-8")
    service.record_stage(
        tmp_path,
        "integration",
        failed,
        "classification research",
        attempts=1,
        session_summaries=["initial model attempt"],
    )

    async def unexpected_invoke(*_args, **_kwargs) -> str:
        raise AssertionError("a passed deterministic revalidation must not call the model")

    events: list[tuple[str, dict]] = []

    async def capture_event(_run, event_type: str, data: dict) -> None:
        events.append((event_type, data))

    monkeypatch.setattr(agent_tools, "invoke_skill", unexpected_invoke)
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", capture_event)

    report = await engine._execute_staged_experiment_implementation(
        run=WorkflowRun(id="revalidated-build", project_path=str(tmp_path)),
        direction="classification research",
        opts={"run_experiment": False},
    )

    assert report["blocking"] is False, report
    assert any(event == "implementation_stage_revalidated" for event, _ in events)
    integration = service.load_build(tmp_path)["stages"]["integration"]
    assert integration["status"] == "accepted"
    assert integration["attempts"] == 1


@pytest.mark.asyncio
async def test_changed_accepted_stage_receives_explicit_stale_fingerprint_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    service = experiment_implementation_build_service
    direction = "classification research"
    service.ensure_blueprint(tmp_path, direction)
    for stage in ML_STAGES:
        report = service.validate_stage(tmp_path, stage.id, direction)
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report, direction)

    data_path = tmp_path / "experiments" / "src" / "data.py"
    data_path.write_text(
        data_path.read_text(encoding="utf-8") + "\nDATA_REVISION = 2\n",
        encoding="utf-8",
    )

    class StaleFindingObserved(RuntimeError):
        pass

    async def capture_stale_finding(
        _skill_name: str,
        arguments: str,
        **_kwargs,
    ) -> str:
        assert "accepted stage fingerprint is stale" in arguments
        assert "stage-owned output changed" in arguments
        raise StaleFindingObserved

    async def ignore_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_tools, "invoke_skill", capture_stale_finding)
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.mark_execution",
        lambda *_args, **_kwargs: None,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", ignore_event)

    with pytest.raises(StaleFindingObserved):
        await engine._execute_staged_experiment_implementation(
            run=WorkflowRun(id="stale-stage-finding", project_path=str(tmp_path)),
            direction=direction,
            opts={"run_experiment": False},
        )


@pytest.mark.asyncio
async def test_stage_stops_when_delegate_edits_frozen_upstream_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "classification research")
    _write_complete_pipeline(tmp_path)

    async def violating_delegate(_skill_name: str, arguments: str, **_kwargs) -> str:
        assert "Stage: data" in arguments
        plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
        plan.write_text("# Illegally replaced upstream plan\n", encoding="utf-8")
        return "edited outside stage ownership"

    async def ignore_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_tools, "invoke_skill", violating_delegate)
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.mark_execution",
        lambda *_args, **_kwargs: None,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", ignore_event)

    report = await engine._execute_staged_experiment_implementation(
        run=WorkflowRun(id="ownership", project_path=str(tmp_path)),
        direction="classification research",
        opts={},
    )

    assert report["blocking"] is True
    build = service.load_build(tmp_path)
    data_record = build["stages"]["data"]
    assert data_record["status"] == "needs_revision"
    assert any(
        "protected upstream/frozen artifacts" in issue
        for issue in data_record["issues"]
    )


@pytest.mark.asyncio
async def test_integration_reachability_finding_reopens_entrypoint_owner_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for test 77: integration must be able to wire train -> eval."""
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "classification research")
    _write_complete_pipeline(tmp_path)

    evaluation_path = tmp_path / "experiments" / "src" / "evaluation.py"
    evaluation_path.write_text(
        evaluation_path.read_text(encoding="utf-8")
        + "\ndef probe_diagnostic(model, batch):\n    return model.forward(batch)\n",
        encoding="utf-8",
    )
    contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["implementation_checks"].append({
        "id": "I2",
        "description": "Probe diagnostic is reachable from the formal entrypoint",
        "evidence": [{
            "path": "experiments/src/evaluation.py",
            "symbols": ["probe_diagnostic"],
        }],
    })
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    for stage in ML_STAGES[:-1]:
        report = service.validate_stage(tmp_path, stage.id, "classification research")
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report, "classification research")
    integration_before = service.validate_stage(
        tmp_path, "integration", "classification research"
    )
    assert not integration_before["passed"]
    assert "experiments/src/train.py" in integration_before["repair_targets"]

    calls: list[str] = []

    async def repair_integration(_skill_name: str, arguments: str, **_kwargs) -> str:
        if "Stage: evaluation" in arguments:
            calls.append("evaluation")
            return "Revalidated unchanged evaluation after entrypoint repair."
        assert "Stage: integration" in arguments
        assert "- experiments/src/train.py" in arguments
        calls.append("integration")
        train_path = tmp_path / "experiments" / "src" / "train.py"
        source = train_path.read_text(encoding="utf-8")
        source = source.replace(
            "from evaluation import evaluate",
            "from evaluation import evaluate, probe_diagnostic",
        ).replace(
            "metrics = evaluate(model, batch)",
            "probe_diagnostic(model, batch)\n    metrics = evaluate(model, batch)",
        )
        train_path.write_text(source, encoding="utf-8")
        return "wired formal entrypoint to probe diagnostic"

    async def ignore_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_tools, "invoke_skill", repair_integration)
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.mark_execution",
        lambda *_args, **_kwargs: None,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", ignore_event)

    final = await engine._execute_staged_experiment_implementation(
        run=WorkflowRun(id="cross-stage-repair", project_path=str(tmp_path)),
        direction="classification research",
        opts={"run_experiment": False},
    )

    assert final["blocking"] is False, final
    assert calls == ["integration", "evaluation"]
    build = service.load_build(tmp_path)
    assert build["stages"]["data"]["attempts"] == 1
    assert build["stages"]["method"]["attempts"] == 1
    assert build["stages"]["training"]["status"] == "accepted"
    assert build["stages"]["evaluation"]["status"] == "accepted"
    assert build["stages"]["integration"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_integration_expands_repair_targets_between_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocker exposed by attempt 1 must be repairable on attempt 2."""
    _seed_contracts(tmp_path)
    service = experiment_implementation_build_service
    service.ensure_blueprint(tmp_path, "classification research")
    _write_complete_pipeline(tmp_path)

    evaluation_path = tmp_path / "experiments" / "src" / "evaluation.py"
    evaluation_path.write_text(
        evaluation_path.read_text(encoding="utf-8")
        + "\ndef late_probe(model, batch):\n    return model.forward(batch)\n",
        encoding="utf-8",
    )
    contract_path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["status"] = "implementation_in_progress"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    for stage in ML_STAGES[:-1]:
        report = service.validate_stage(tmp_path, stage.id, "classification research")
        assert report["passed"], report
        service.record_stage(tmp_path, stage.id, report, "classification research")
    integration_before = service.validate_stage(
        tmp_path, "integration", "classification research"
    )
    assert not integration_before["passed"]
    assert integration_before["repair_targets"] == []

    prompts: list[str] = []

    async def progressive_repair(
        _skill_name: str,
        arguments: str,
        **_kwargs,
    ) -> str:
        if "Stage: evaluation" in arguments:
            return "Revalidated unchanged evaluation after entrypoint repair."
        prompts.append(arguments)
        owned_section = arguments.split(
            "Files owned by this stage:\n", 1
        )[1].split("\n\nRead-only upstream implementation inputs:", 1)[0]
        if len(prompts) == 1:
            assert "- experiments/src/train.py" not in owned_section
            patch_path = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
            patch = json.loads(patch_path.read_text(encoding="utf-8"))
            patch["checks"].append({
                "check_id": "I-LATE",
                "description": "Late probe is reachable from the entrypoint",
                "evidence": [{
                    "path": "experiments/src/evaluation.py",
                    "symbols": ["late_probe"],
                }],
            })
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            return "registered typed evidence for the late probe"

        assert "- experiments/src/train.py" in owned_section
        train_path = tmp_path / "experiments" / "src" / "train.py"
        source = train_path.read_text(encoding="utf-8")
        source = source.replace(
            "from evaluation import evaluate",
            "from evaluation import evaluate, late_probe",
        ).replace(
            "metrics = evaluate(model, batch)",
            "late_probe(model, batch)\n    metrics = evaluate(model, batch)",
        )
        train_path.write_text(source, encoding="utf-8")
        return "wired the newly registered probe into the formal entrypoint"

    events: list[tuple[str, dict]] = []

    async def capture_event(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(agent_tools, "invoke_skill", progressive_repair)
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.mark_execution",
        lambda *_args, **_kwargs: None,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", capture_event)

    final = await engine._execute_staged_experiment_implementation(
        run=WorkflowRun(id="progressive-integration", project_path=str(tmp_path)),
        direction="classification research",
        opts={"run_experiment": False},
    )

    assert final["blocking"] is False, final
    assert len(prompts) == 2
    assert any(
        event == "implementation_stage_targets_expanded"
        and "experiments/src/train.py" in payload["new_targets"]
        for event, payload in events
    )
    build = service.load_build(tmp_path)
    assert build["stages"]["integration"]["status"] == "accepted"
    assert build["stages"]["integration"]["attempts"] == 2


@pytest.mark.asyncio
async def test_pure_implementation_revision_skips_primary_design_and_specialists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    events: list[str] = []

    async def capture_event(_run, event_type: str, _data: dict) -> None:
        events.append(event_type)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("implementation-only repair must not rerun broad model owners")

    monkeypatch.setattr(engine, "_emit", capture_event)
    monkeypatch.setattr(engine, "_execute_profile_specialists", forbidden)
    monkeypatch.setattr(engine, "_execute_node", forbidden)
    run = WorkflowRun(id="routed-revision", project_path=str(tmp_path))
    node = next(item for item in engine._get_default_nodes() if item.id == "exp-design")
    diagnostics = {
        "issues": ["formal entrypoint cannot reach probe_diagnostic"],
        "findings": [{
            "id": "IMPL-MECH-I2-UNREACHABLE",
            "category": "implementation",
            "target_files": [
                "experiments/src/train.py",
                "experiments/src/evaluation.py",
            ],
        }],
        "repair_scope": {
            "target_files": [
                "experiments/src/train.py",
                "experiments/src/evaluation.py",
            ],
        },
    }

    result = await engine._revise_node_from_gate(
        node,
        run,
        diagnostics,
        1,
        1,
        "",
        "classification research",
        "balanced",
        "draft",
        {"run_experiment": False},
    )

    assert "staged owner" in result
    assert events == ["implementation_repair_routed"]


@pytest.mark.asyncio
async def test_mixed_integration_findings_skip_primary_design_and_specialists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    events: list[str] = []

    async def capture_event(_run, event_type: str, _data: dict) -> None:
        events.append(event_type)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("integration-owned repair must not rerun broad model owners")

    monkeypatch.setattr(engine, "_emit", capture_event)
    monkeypatch.setattr(engine, "_execute_profile_specialists", forbidden)
    monkeypatch.setattr(engine, "_execute_node", forbidden)
    run = WorkflowRun(id="mixed-routed-revision", project_path=str(tmp_path))
    node = next(item for item in engine._get_default_nodes() if item.id == "exp-design")
    diagnostics = {
        "issues": ["missing output key", "RUN_SPEC has no explicit seed list"],
        "findings": [
            {
                "id": "IMPL-DATA-KEY",
                "category": "staged_implementation",
                "target_files": ["experiments/METHOD_CONTRACT.json"],
            },
            {
                "id": "REPRO-SEEDS",
                "category": "reproducibility",
                "target_files": ["experiments/RUN_SPEC.json"],
            },
        ],
        "repair_scope": {
            "target_files": [
                "experiments/METHOD_CONTRACT.json",
                "experiments/RUN_SPEC.json",
            ],
        },
    }

    result = await engine._revise_node_from_gate(
        node,
        run,
        diagnostics,
        1,
        1,
        "",
        "classification research",
        "balanced",
        "draft",
        {"run_experiment": False},
    )

    assert "staged owner" in result
    assert events == ["implementation_repair_routed"]
