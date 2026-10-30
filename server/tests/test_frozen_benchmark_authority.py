"""Independent pins separate historical benchmarks from nonexecuted future code."""

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from server.services import frozen_benchmark_authority as authority
from server.services.protocol_conformance import build_protocol_conformance_ledger
from server.tests._scientific_slide_fixture import write_current_slide_bundle


SETTINGS = {"direction": "Bound structural benchmark study", "evidence_mode": "synthetic_preview",
            "target_venue": "ICLR", "research_family": "auto", "study_archetype": "auto"}


def _put(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _pins(value):
    root, history, reference = value["root"], value["history"], value["reference"]
    return {"historical_inputs_pin": authority.historical_inputs_digest(history, SETTINGS),
            "benchmark_inventory_pin": authority.benchmark_inventory_digest(reference),
            "prospective_inventory_pin": authority.prospective_inventory_digest(root),
            "current_input_digest": authority._input_digest(root, SETTINGS)}


@pytest.fixture
def frozen(tmp_path):
    reference, history, root = (tmp_path / name for name in ("frozen-reference", "original-authority", "future-code-copy"))
    write_current_slide_bundle(reference)
    _put(reference, "ideas/ideas.md", "Frozen study proposal\n")
    _put(reference, "ideas/novelty_report.md", "Source-bound novelty review\n")
    _put(reference, "experiments/EXPERIMENT_PLAN.md", "Registered structural benchmark with fixed claims and controls.\n")
    method = authority._json(reference, "experiments/METHOD_CONTRACT.json")
    method.update(status="implemented", idea_contract_path="ideas/SELECTED_IDEA.json",
                  idea_contract_sha256=_sha(reference / "ideas/SELECTED_IDEA.json"),
                  integration_verdict={"validator": "implementation-integration-v1", "output_sha256": "a" * 64},
                  scientific_scene={"schema": 1, "objects": [{"id": "one", "kind": "input", "label": "Scientific input",
                      "source_path": "experiments/EXPERIMENT_PLAN.md"}], "relations": []},
                  mechanism_coverage=[{"idea_mechanism_id": "M1", "implementation_check_ids": ["old-check"], "status": "implemented"}],
                  implementation_checks=[{"id": "old-check", "description": "Frozen source identity",
                      "evidence": [{"path": "experiments/EXPERIMENT_PLAN.md"}]}])
    _put(reference, "experiments/METHOD_CONTRACT.json", method)
    config = {"research_contract": {"execution_authorized": False},
              "execution": {"execution_prohibited_in_this_stage": True}, "data": {"old_scheme": "structural"}}
    _put(reference, "experiments/configs/main.yaml", yaml.safe_dump(config))
    run = {"schema": 1, "seeds": [1729], "execution_status": "not_executed",
           "execution_prohibited_in_this_stage": True, "run_experiment_authorized": False,
           "scientific_outputs": {"primary_metric": "score"}}
    _put(reference, "experiments/RUN_SPEC.json", run)
    history.mkdir()
    for name in (*authority._INPUTS, "experiments/RUN_SPEC.json"):
        _put(history, name, (reference / name).read_text(encoding="utf-8"))
    simulation = authority._json(reference, authority._SIMULATION)
    simulation["replicate_contract"] = {"seed_ids": [1729], "unit": "random_seed"}
    package = simulation["evidence_package"]
    parameters = {"schema": 1, "simulation_id": simulation["simulation_id"], "simulation_seed": simulation["simulation_seed"],
                  "replicate_seeds": [1729], "registered_models": simulation["registered_model_suite"],
                  "registered_axes": simulation["registered_ranking_axes"],
                  "input_files": {name: _sha(history / name) for name in (
                      "experiments/configs/main.yaml", "experiments/RUN_SPEC.json", "experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json")}}
    _put(reference, package["scenario_parameters"], parameters)
    for key, name in (("scenario_config", "experiments/configs/main.yaml"), ("run_spec", "experiments/RUN_SPEC.json"),
                      ("method_contract", "experiments/METHOD_CONTRACT.json")):
        _put(reference, package[key], (history / name).read_text(encoding="utf-8"))
    for key in ("scenario_parameters", "scenario_config", "run_spec", "method_contract"):
        package[key + "_sha256"] = _sha(reference / package[key])
    for item in simulation["data_files"]:
        item["sha256"] = _sha(reference / item["path"])
    _put(reference, authority._SIMULATION, simulation)
    _put(reference, authority._PLANNED, {"schema": 5, "evidence_mode": "synthetic_preview",
        "input_bundle_sha256": authority._input_digest(history, SETTINGS), "publication_style": {"target_venue": "ICLR"}})
    shutil.copytree(reference, root)
    source = _put(root, "experiments/src/new_method.py", "raise RuntimeError('Future code must never execute in this proof')\n")
    changed_method = copy.deepcopy(method)
    changed_method["implementation_checks"] = [{"id": "new-check", "description": "Current source identity",
                                                 "evidence": [{"path": "experiments/src/new_method.py"}]}]
    changed_method["mechanism_coverage"][0]["implementation_check_ids"] = ["new-check"]
    changed_method.update(implementation_level="executable_experiment_pipeline", code_validation_level="V1_pure_local",
                          scientific_execution_performed=False)
    _put(root, "experiments/METHOD_CONTRACT.json", changed_method)
    config["data"] = {"new_prospective_scheme": "not the frozen simulator"}
    _put(root, "experiments/configs/main.yaml", yaml.safe_dump(config))
    findings = [{"id": "EXECUTION-PENDING", "status": "unvalidated", "area": "future_code",
                 "declared": "Requires independent data and consent", "observed": "No research execution",
                 "evidence": ["experiments/EXPERIMENT_PLAN.md", "experiments/src/new_method.py"]}]
    _put(root, authority._READINESS, build_protocol_conformance_ledger(root, findings))
    _put(root, authority._CODE, {"schema": 1, "validation_level": "V1_pure_local", "code_ready_verified": True,
        "scientific_execution_performed": False, "training_performed": False, "research_evidence": False,
        "experiment_authorized": False, "source_sha256": {"experiments/src/new_method.py": _sha(source)}})
    value = {"root": root, "history": history, "reference": reference}
    value["pins"] = _pins(value)
    return value


def _prepare(value, **overrides):
    return authority.prepare_frozen_benchmark_authority(value["root"], value["history"], value["reference"], SETTINGS,
                                                        **{**value["pins"], **overrides})


def _refresh_future_readiness(value):
    root = value["root"]
    old = authority._json(root, authority._READINESS)
    _put(root, authority._READINESS, build_protocol_conformance_ledger(root, old["findings"]))
    value["pins"] = _pins(value)


def test_frozen_source_reuse_proof_is_readonly_byte_stable_and_never_resigns_manifests_or_accepts_workflow(frozen):
    before = {name: _files(frozen[name]) for name in ("root", "history", "reference")}
    proof = _prepare(frozen)
    assert proof["original_generation_input_sha256"] != proof["current_prospective_input_sha256"]
    assert proof["benchmark_scope"]["registered_model_suite"] == authority._json(frozen["reference"], authority._SIMULATION)["registered_model_suite"]
    assert proof["prospective_scope"]["implementation_is_benchmark_generator"] is False
    assert proof["manifests_resigned"] is proof["scientific_execution_performed"] is proof["workflow_acceptance_granted"] is False
    assert proof == _prepare(frozen)
    assert authority.validate_frozen_benchmark_authority(frozen["root"], proof, frozen["history"], frozen["reference"], SETTINGS, **frozen["pins"]) == proof
    assert all(_files(frozen[name]) == before[name] for name in before)


@pytest.mark.parametrize("pin", ["historical_inputs_pin", "benchmark_inventory_pin", "prospective_inventory_pin", "current_input_digest"])
def test_every_independently_observed_owner_pin_is_required_not_a_self_signed_boolean(frozen, pin):
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="owner pins"):
        _prepare(frozen, **{pin: "0" * 64})


@pytest.mark.parametrize("name", ["ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md"])
def test_recomputed_current_hash_does_not_authorize_changed_scientific_problem_claims_plan_or_public_labels(frozen, name):
    path = frozen["root"] / name
    path.write_bytes(path.read_bytes() + b"\nChanged public scientific content\n")
    pins = _pins(frozen)
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="selected claims"):
        _prepare(frozen, **pins)


@pytest.mark.parametrize("field", ["scientific_scene", "evaluation_contract", "claim_evidence_plan", "mechanism_coverage"])
def test_even_rebound_new_code_cannot_change_scientific_method_fields(frozen, field):
    path = frozen["root"] / "experiments/METHOD_CONTRACT.json"
    method = json.loads(path.read_text())
    method[field] = {"invented": True} if field != "mechanism_coverage" else [{"idea_mechanism_id": "changed", "status": "implemented"}]
    _put(frozen["root"], path.relative_to(frozen["root"]).as_posix(), method)
    with pytest.raises(authority.FrozenBenchmarkAuthorityError):
        _prepare(frozen, **_pins(frozen))


@pytest.mark.parametrize("defect", ["numeric", "source", "variant", "provenance", "new_numeric"])
def test_original_numeric_and_plot_source_provenance_hashes_cannot_be_resigned_by_the_proof(frozen, defect):
    simulation = authority._json(frozen["root"], authority._SIMULATION)
    relative = {"numeric": simulation["data_files"][0]["path"], "source": simulation["figure_files"][0]["source"],
                "variant": simulation["figure_files"][0]["outputs"]["png"],
                "provenance": simulation["evidence_package"]["raw_measurements"]}.get(defect)
    if relative:
        path = frozen["root"] / relative
        path.write_bytes(path.read_bytes() + b"untrusted-change")
    else:
        _put(frozen["root"], "experiments/results/extra.csv", "unit,value\nforeign,999\n")
    with pytest.raises(ValueError):
        _prepare(frozen)


def test_unknown_original_generation_options_are_not_just_ignored_as_runtime_metadata(frozen):
    changed = {**SETTINGS, "target_venue": "Different venue"}
    pins = {**frozen["pins"], "historical_inputs_pin": authority.historical_inputs_digest(frozen["history"], changed),
            "current_input_digest": authority._input_digest(frozen["root"], changed)}
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="original planned"):
        authority.prepare_frozen_benchmark_authority(frozen["root"], frozen["history"], frozen["reference"], changed, **pins)


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis", "executed", "design_only"])
def test_benchmark_proof_cannot_relabel_frozen_structural_evidence_as_other_modes(frozen, mode):
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="structural synthetic"):
        authority.historical_inputs_digest(frozen["history"], {**SETTINGS, "evidence_mode": mode})


@pytest.mark.parametrize("field", ["replicate_seeds", "registered_models", "input_files"])
def test_original_generator_registration_must_match_historical_inputs_not_a_fabricated_archive(frozen, field):
    reference = frozen["reference"]
    simulation = authority._json(reference, authority._SIMULATION)
    path = simulation["evidence_package"]["scenario_parameters"]
    parameters = authority._json(reference, path)
    parameters[field] = [] if field != "input_files" else {"fake": "0" * 64}
    _put(reference, path, parameters)
    simulation["evidence_package"]["scenario_parameters_sha256"] = _sha(reference / path)
    for item in simulation["data_files"]:
        if item["path"] == path:
            item["sha256"] = _sha(reference / path)
    _put(reference, authority._SIMULATION, simulation)
    (frozen["root"] / path).write_bytes((reference / path).read_bytes())
    (frozen["root"] / authority._SIMULATION).write_bytes((reference / authority._SIMULATION).read_bytes())
    with pytest.raises(ValueError, match="registration|contract"):
        _prepare(frozen, **_pins(frozen))


def test_forged_proof_field_is_reconstructed_from_external_pins_and_refused(frozen):
    proof = _prepare(frozen)
    proof["workflow_acceptance_granted"] = True
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="forged"):
        authority.validate_frozen_benchmark_authority(frozen["root"], proof, frozen["history"], frozen["reference"], SETTINGS, **frozen["pins"])


def test_missing_original_authority_cannot_use_current_sources_as_its_history(frozen):
    (frozen["history"] / "experiments/configs/main.yaml").unlink()
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="missing"):
        _prepare(frozen)


def test_current_code_readiness_is_separate_and_must_not_claim_training(frozen):
    payload = authority._json(frozen["root"], authority._CODE)
    payload["training_performed"] = True
    _put(frozen["root"], authority._CODE, payload)
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="nonexecuted"):
        _prepare(frozen, **_pins(frozen))


def test_current_source_bound_scene_may_be_revised_without_becoming_historical_generator_evidence(frozen):
    root = frozen["root"]
    method = authority._json(root, "experiments/METHOD_CONTRACT.json")
    method["scientific_scene"] = {"schema": 1, "objects": [{"id": "parent", "kind": "input",
        "label": "Recorded input", "source_path": "experiments/EXPERIMENT_PLAN.md",
        "source_sha256": _sha(root / "experiments/EXPERIMENT_PLAN.md")}], "relations": []}
    _put(root, "experiments/METHOD_CONTRACT.json", method)
    _refresh_future_readiness(frozen)
    proof = _prepare(frozen)
    assert proof["prospective_scope"]["scene_is_historical_benchmark_input"] is False
    assert proof["prospective_scope"]["scientific_scene_sha256"] == authority._digest(method["scientific_scene"])
    assert proof["workflow_acceptance_granted"] is False


@pytest.mark.parametrize("defect", ["missing_source_hash", "stale_source_hash", "foreign_source", "unsupported_schema", "absent_endpoint"])
def test_revised_scene_is_not_a_blanket_semantic_ignore_and_needs_valid_source_bound_schema(frozen, defect):
    root = frozen["root"]
    source = "experiments/EXPERIMENT_PLAN.md"
    scene = {"schema": 1, "objects": [{"id": "parent", "kind": "input", "label": "Recorded input",
              "source_path": source, "source_sha256": _sha(root / source)}], "relations": []}
    if defect == "missing_source_hash":
        del scene["objects"][0]["source_sha256"]
    elif defect == "stale_source_hash":
        scene["objects"][0]["source_sha256"] = "0" * 64
    elif defect == "foreign_source":
        scene["objects"][0]["source_path"] = "../foreign.py"
    elif defect == "unsupported_schema":
        scene["schema"] = 99
    else:
        scene["relations"] = [{"from": "parent", "to": "absent", "kind": "data"}]
    method = authority._json(root, "experiments/METHOD_CONTRACT.json")
    method["scientific_scene"] = scene
    _put(root, "experiments/METHOD_CONTRACT.json", method)
    _refresh_future_readiness(frozen)
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="scene"):
        _prepare(frozen)


def test_new_owner_reports_are_explicitly_current_context_not_rewritten_historical_generation_inputs(frozen):
    root, history, reference = frozen["root"], frozen["history"], frozen["reference"]
    original_inputs, original_bundle = _files(history), _files(reference)
    original_generation = _prepare(frozen)["original_generation_input_sha256"]
    _put(root, "ideas/ideas.md", "Fresh source-owner synthesis preserves the separately frozen selected hypothesis.\n")
    _put(root, "ideas/novelty_report.md", "Fresh source-owner citation and novelty reasoning, not past simulator input.\n")
    _put(root, "literature/survey.md", "Current literature review; the workflow literature gate must independently verify it.\n")
    _put(root, "literature/references.bib", "@article{current,title={Bound current reference}}\n")
    _put(root, "literature/CITATION_VERIFICATION.json", {"schema": 1, "owner": "current_literature_context"})
    frozen["pins"] = _pins(frozen)
    proof = _prepare(frozen)
    assert proof["original_generation_input_sha256"] == original_generation
    assert proof["reports_were_used_for_historical_generation"] is False
    assert proof["generation_inputs_are_archived_not_current_context"] is True
    expected = {name: _sha(root / name) for name in ("ideas/ideas.md", "ideas/novelty_report.md",
        "literature/survey.md", "literature/references.bib", "literature/CITATION_VERIFICATION.json")}
    assert proof["current_owner_report_context"] == expected
    assert proof["workflow_acceptance_granted"] is False
    assert _files(history) == original_inputs and _files(reference) == original_bundle


@pytest.mark.parametrize("relative", ["ideas/ideas.md", "ideas/novelty_report.md", "literature/new_review.md"])
def test_new_owner_report_edits_require_new_independent_context_pins_not_old_readiness(frozen, relative):
    old = _prepare(frozen)
    _put(frozen["root"], relative, "Changed current owner report.\n")
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="owner pins"):
        _prepare(frozen)
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="forged"):
        authority.validate_frozen_benchmark_authority(frozen["root"], old, frozen["history"], frozen["reference"], SETTINGS,
                                                      **_pins(frozen))


def test_changed_original_report_is_still_generation_drift_even_with_a_new_current_context(frozen):
    _put(frozen["history"], "ideas/ideas.md", "Altered historical generation report.\n")
    with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="original planned"):
        _prepare(frozen, **_pins(frozen))


def test_real_passing_integration_producer_changes_only_runtime_hash_without_resigning_benchmark(frozen):
    from server.contracts.implementation_evidence import IntegrationVerdict
    from server.services.method_contract_persistence import finalize_from_integration_verdict

    root, history, reference = frozen["root"], frozen["history"], frozen["reference"]
    method_path, idea_path = root / "experiments/METHOD_CONTRACT.json", root / "ideas/SELECTED_IDEA.json"
    identity = authority._scientific_method(json.loads(method_path.read_text()))
    protected = {name: _files(frozen[name]) for name in ("history", "reference")}
    benchmark = {name: (root / name).read_bytes() for name in authority.benchmark_inventory(root)}
    assert finalize_from_integration_verdict(method_path, idea_path, Path("ideas/SELECTED_IDEA.json"),
                                             IntegrationVerdict(passed=True, report_sha256="b" * 64, issues=()))
    actual = json.loads(method_path.read_text())
    assert actual["integration_verdict"] == {"validator": "implementation-integration-v1", "output_sha256": "b" * 64}
    assert authority._scientific_method(actual) == identity
    _refresh_future_readiness(frozen)
    before = _files(root)
    proof = _prepare(frozen)
    assert authority.validate_frozen_benchmark_authority(root, proof, history, reference, SETTINGS, **frozen["pins"]) == proof
    assert proof["manifests_resigned"] is proof["scientific_execution_performed"] is proof["workflow_acceptance_granted"] is False
    assert _files(root) == before
    assert all((root / name).read_bytes() == value for name, value in benchmark.items())
    assert all(_files(frozen[name]) == value for name, value in protected.items())


@pytest.mark.parametrize("defect", ["validator", "extra_claim", "malformed_hash", "missing_hash", "non_object"])
def test_runtime_digest_exemption_does_not_ignore_unknown_verdict_science_or_invalid_schema(frozen, defect):
    method = authority._json(frozen["root"], "experiments/METHOD_CONTRACT.json")
    baseline = authority._scientific_method(method)
    if defect == "validator":
        method["integration_verdict"]["validator"] = "forged-validator"
    elif defect == "extra_claim":
        method["integration_verdict"]["claim_statement"] = "Unsupported observed transfer benefit"
    elif defect == "malformed_hash":
        method["integration_verdict"]["output_sha256"] = "not-a-digest"
    elif defect == "missing_hash":
        del method["integration_verdict"]["output_sha256"]
    else:
        method["integration_verdict"] = True
    if defect in {"validator", "extra_claim"}:
        assert authority._scientific_method(method) != baseline
    else:
        with pytest.raises(authority.FrozenBenchmarkAuthorityError, match="integration_verdict"):
            authority._scientific_method(method)
