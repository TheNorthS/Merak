"""Pure constraint propagation/cache tests; no model, workflow or original project writes."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.services import paper_draft_state
from server.services.paper_draft_preparation import _reuse_decision
from server.services.paper_scientific_freeze import authoring_signature
from server.services.workflow_user_constraints import (
    MAX_NODE_INPUT_BYTES, USER_CONSTRAINTS_PROMPT_VERSION,
    node_input_constraints, render_user_constraints,
)


def _constraints() -> dict:
    return {"scope": "Use only supplied benchmark records; do not claim research execution.",
        "nested": {"null": None, "false": False, "true": True, "zero": 0, "float": 1.5,
            "ordered": ["condition B", "condition A"]},
        "authoring_brief": "跨领域已注册证据约束。 " * 600 + "STRICT_TAIL: leave unresolved scientific claims unresolved."}


def _options() -> dict:
    return {"target_venue": "ICLR", "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
        "node_inputs": _constraints(), "provider": {"api_key": "PRIVATE_PROVIDER_SECRET"},
        "environment": {"TOKEN": "PRIVATE_ENV_SECRET"}, "unrelated_runtime": "PRIVATE_RUNTIME_SECRET"}


def _bytes(root: Path) -> dict:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object(), ("not", "JSON"),
    {1: "non-string key"}, {"nested": {False: "non-string key"}}])
def test_only_finite_json_values_and_string_keys_are_accepted(value):
    with pytest.raises(ValueError):
        node_input_constraints({"node_inputs": {"constraint": value}})


@pytest.mark.parametrize("value", [None, [], "invalid", 3])
def test_top_level_constraints_must_be_an_explicit_object(value):
    with pytest.raises(ValueError, match="JSON object"):
        node_input_constraints({"node_inputs": value})


def test_normalization_is_independent_stable_typed_and_never_reads_other_options():
    options = _options()
    before = copy.deepcopy(options)
    normalized = node_input_constraints(options)
    assert normalized == options["node_inputs"] and options == before
    assert normalized is not options["node_inputs"]
    assert normalized["nested"]["false"] is False and normalized["nested"]["zero"] == 0
    assert normalized["nested"]["null"] is None
    assert normalized["nested"]["ordered"] == ["condition B", "condition A"]
    prompt = render_user_constraints(options)
    assert "STRICT_TAIL" in prompt and "跨领域" in prompt and "do not override frozen upstream contracts" in prompt
    assert not any(secret in prompt for secret in ("PRIVATE_PROVIDER_SECRET", "PRIVATE_ENV_SECRET", "PRIVATE_RUNTIME_SECRET"))
    assert render_user_constraints({}) == "" and render_user_constraints({"node_inputs": {}}) == ""
    normalized["nested"]["ordered"].append("Independent copy")
    assert options == before


def test_fields_and_utf8_size_are_bounded_without_truncating_any_valid_payload():
    with pytest.raises(ValueError, match="64 fields"):
        node_input_constraints({"node_inputs": {str(index): index for index in range(65)}})
    prefix_bytes = len(json.dumps({"brief": ""}, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    accepted = {"brief": "x" * (MAX_NODE_INPUT_BYTES - prefix_bytes)}
    assert node_input_constraints({"node_inputs": accepted}) == accepted
    assert accepted["brief"] in render_user_constraints({"node_inputs": accepted})
    with pytest.raises(ValueError, match="32 KiB"):
        node_input_constraints({"node_inputs": {"brief": accepted["brief"] + "x"}})
    with pytest.raises(ValueError, match="32 KiB"):
        node_input_constraints({"node_inputs": {"brief": "汉" * 12000}})


def test_invalid_utf8_or_cyclic_constraint_fails_closed():
    with pytest.raises(ValueError, match="UTF-8"):
        node_input_constraints({"node_inputs": {"invalid": "\ud800"}})
    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ValueError, match="nesting"):
        node_input_constraints({"node_inputs": cycle})


def test_api_request_uses_the_same_strict_contract():
    from server.api.workflow import WorkflowRunRequest

    raw = _constraints()
    request = WorkflowRunRequest(node_ids=["paper"], project_path="unused-pure-fixture", node_inputs=raw)
    assert request.node_inputs == node_input_constraints({"node_inputs": raw})
    for value in (float("nan"), float("inf"), object(), ("tuple",)):
        with pytest.raises(ValueError):
            WorkflowRunRequest(node_ids=["paper"], project_path="unused-pure-fixture", node_inputs={"invalid": value})


@pytest.mark.parametrize("stage_id", [
    "blueprint", "introduction", "related_work", "method", "experiments", "results",
    "discussion", "limitations", "conclusion", "front_matter", "consistency",
])
def test_every_isolated_manuscript_author_and_consistency_receives_complete_constraints(tmp_path, stage_id):
    from server.services.paper_drafting import PaperDraftingService
    from server.tests._staged_paper_drafting_support import seed_project

    seed_project(tmp_path)
    options, service = _options(), PaperDraftingService()
    service.prepare(tmp_path, options)
    before = _bytes(tmp_path)
    prompt = service.build_stage_prompt(tmp_path, stage_id, options,
        revision_issues=["Target artifact: paper/sections/05_results.tex; preserve only descriptive table scope."])
    assert render_user_constraints(options) in prompt
    assert "STRICT_TAIL: leave unresolved scientific claims unresolved." in prompt
    assert not any(secret in prompt for secret in ("PRIVATE_PROVIDER_SECRET", "PRIVATE_ENV_SECRET", "PRIVATE_RUNTIME_SECRET"))
    assert prompt.index("STRICT_TAIL") < prompt.index("The previous bounded draft failed local review")
    # The only prompt-side output is the existing trusted authoring asset inventory.
    after = _bytes(tmp_path)
    for name, raw in before.items():
        if name != "paper/AUTHORING_ASSET_MANIFEST.json":
            assert after[name] == raw
    assert not list((tmp_path / ".merak").glob("skill-invocations/*.json"))


def test_invalid_constraints_are_rejected_before_authoring_inventory_can_write(tmp_path):
    from server.services.paper_stage_prompts import build_stage_prompt

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid user constraints must fail before any project mutation")
    with pytest.raises(ValueError, match="32 KiB"):
        build_stage_prompt(paths={"root": tmp_path}, stage_id="results",
            options={"node_inputs": {"brief": "x" * 40000}}, revision_issues=None,
            section_by_id={}, author_order=(), inventory=forbidden, write_assets=forbidden)
    assert not list(tmp_path.rglob("*"))


def test_normal_workflow_node_and_isolated_section_share_exact_constraint_renderer(tmp_path, monkeypatch):
    from server.workflows.engine import WorkflowEngine
    from server.workflows.models import WorkflowRun

    host = WorkflowEngine()
    node = next(item for item in host._get_default_nodes() if item.id == "idea")
    monkeypatch.setattr(host, "_input_idea", lambda *_args: "Pure node context")
    options = _options()
    prompt = host._build_node_input(node, "Generic domain", WorkflowRun(project_path=str(tmp_path), options=options))
    assert prompt.endswith(render_user_constraints(options))
    assert "PRIVATE_PROVIDER_SECRET" not in prompt


def test_signature_options_round_trip_and_partial_gate_resolution_are_idempotent():
    normalized = paper_draft_state.signature_options(_options())
    assert normalized["user_constraints_prompt_version"] == USER_CONSTRAINTS_PROMPT_VERSION
    assert paper_draft_state.signature_options(normalized) == normalized
    assert paper_draft_state.gate_signature_options({}, normalized) == normalized
    assert paper_draft_state.gate_signature_options(None, normalized) == normalized
    changed = paper_draft_state.gate_signature_options({"node_inputs": {}}, normalized)
    assert changed["node_inputs"] == {} and changed != normalized
    assert changed["user_constraints_prompt_version"] == USER_CONSTRAINTS_PROMPT_VERSION


def test_constraint_changes_bind_authoring_identity_but_runtime_budgets_and_provider_keys_do_not(tmp_path):
    options = _options()
    baseline = authoring_signature(tmp_path, options)
    changed = copy.deepcopy(options)
    changed["node_inputs"]["scope"] = "Different explicit scientific scope"
    assert authoring_signature(tmp_path, changed) != baseline
    assert authoring_signature(tmp_path, paper_draft_state.signature_options(options)) == baseline
    changed = {**options, "max_revision_rounds": 1, "checkpoint_timeout_seconds": 2, "provider": "Other private settings"}
    assert authoring_signature(tmp_path, changed) == baseline


@pytest.mark.parametrize("fallback", ["source_signature", "authoring_signature", "identical_inputs"])
def test_old_constraint_unaware_completed_sections_cannot_reuse_any_legacy_signature_fallback(fallback):
    current = paper_draft_state.signature_options(_options())
    previous_options = copy.deepcopy(current)
    previous_options.pop("user_constraints_prompt_version")
    previous = {"schema_version": 3, "authoring_options": previous_options, "authoring_inputs": {"plan": "same"},
        "source_signature": "source-new" if fallback == "source_signature" else "source-old",
        "authoring_signature": "author-new" if fallback == "authoring_signature" else "author-old",
        "stages": {"results": {"status": "completed"}}}
    result = _reuse_decision(previous, "source-new", "author-new", {"plan": "same"}, current, 3)
    assert result == {"reusable": False, "literature_only": False, "literature_content": False}


def test_current_constraints_reuse_unchanged_sections_and_preserve_literature_only_policy():
    current = paper_draft_state.signature_options(_options())
    previous = {"schema_version": 3, "authoring_options": current, "authoring_inputs": {"literature/survey.md": "old"},
        "source_signature": "same", "authoring_signature": "same-author", "stages": {"results": {"status": "completed"}}}
    assert _reuse_decision(previous, "same", "same-author", previous["authoring_inputs"], current, 3)["reusable"]
    result = _reuse_decision(previous, "new", "new-author", {"literature/survey.md": "new"}, current, 3)
    assert result == {"reusable": True, "literature_only": True, "literature_content": True}


@pytest.mark.parametrize("old_contract", [True, 0, 2, None])
def test_old_or_malformed_prompt_contract_cannot_reuse_completed_sections(old_contract):
    current = paper_draft_state.signature_options(_options())
    prior = {**current, "user_constraints_prompt_version": old_contract}
    previous = {"schema_version": 3, "source_signature": "same", "authoring_signature": "same",
        "authoring_options": prior, "authoring_inputs": {}}
    assert _reuse_decision(previous, "same", "same", {}, current, 3)["reusable"] is False


def test_normal_prepare_archives_old_constraint_unaware_sections_without_resigning_them(tmp_path):
    from server.services.paper_drafting import PaperDraftingService
    from server.tests._staged_paper_drafting_support import seed_project

    seed_project(tmp_path)
    service, options = PaperDraftingService(), _options()
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    section = paths["sections"] / "05_results.tex"
    section.write_text("Existing authored claim requiring explicit bounded-scope re-authoring.", encoding="utf-8")
    service.mark_stage(paths, "results", "completed", attempt=1, review={"passed": True, "issues": []})
    previous = json.loads(paths["state"].read_text(encoding="utf-8"))
    previous["authoring_options"].pop("user_constraints_prompt_version")
    paths["state"].write_text(json.dumps(previous), encoding="utf-8")
    source_before = {path: path.read_bytes() for path in service.authoring_source_paths(tmp_path) if path.is_file()}
    body = section.read_bytes()
    state = service.prepare(tmp_path, options)
    assert state["stages"]["results"]["status"] == "pending"
    assert not section.exists()
    archived = list((paths["paper"] / "revisions").rglob("05_results.tex"))
    assert len(archived) == 1 and archived[0].read_bytes() == body
    assert all(path.read_bytes() == raw for path, raw in source_before.items())
    assert not list((tmp_path / ".merak").glob("skill-invocations/*.json"))


def test_malformed_persisted_authoring_options_fail_as_a_known_contract_error():
    current = paper_draft_state.signature_options(_options())
    with pytest.raises(ValueError, match="authoring_options"):
        _reuse_decision({"schema_version": 3, "authoring_options": ["malformed"], "authoring_inputs": {}},
            "same", "same", {}, current, 3)
