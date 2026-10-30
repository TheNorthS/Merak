"""Producer declarations, not option aliases, decide model/runtime execution."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.services.figure_execution_policy import (
    FIGURE_RUNTIME_SERVICE, resolve_figure_execution_policy,
)
from server.services.figure_routing import recommend_figure_route
from server.services.node_execution_contract import resolve_execution_contract
from server.services.skill_orchestrator import skill_orchestrator


def _asset(identity: str, strategy: str) -> dict:
    nature = {
        "deterministic_architecture": "conceptual",
        "deterministic_template": "standard_protocol",
        "deterministic_plot": "quantitative",
        "model_composed_full_svg": "conceptual",
        "model_generated_image": "naturalistic",
    }[strategy]
    raw = {"id": identity, "kind": "figure", "figure_nature": nature,
           "production_strategy": strategy}
    return {**raw, **recommend_figure_route(raw)}


def _write_specs(root: Path, figures: list[dict], **updates: object) -> Path:
    path = root / "figures/FIGURE_SPECS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 4, "publication_label_schema": 1,
                                "production_policy_schema": 1,
                                "figures": figures, **updates}), encoding="utf-8")
    return path


def test_complete_deterministic_portfolio_has_runtime_owner_and_no_model_policy(tmp_path: Path) -> None:
    figures = [_asset("method", "deterministic_architecture"),
               _asset("protocol", "deterministic_template"),
               _asset("results", "deterministic_plot")]
    path = _write_specs(tmp_path, figures)
    before = path.read_bytes()
    contract = resolve_execution_contract("figure", {}, project_path=tmp_path)
    assert contract.kind == "runtime_owned"
    assert contract.runtime_service == FIGURE_RUNTIME_SERVICE
    assert not contract.policy_required and not contract.blocking_issues
    policy = resolve_figure_execution_policy(tmp_path)
    assert policy.assets == tuple(figures)
    assert policy.model_skills == ()
    plan = skill_orchestrator.select("figure", "/paper-figure", str(tmp_path), {})
    assert plan.execution_kind == "runtime_owned"
    assert plan.primary == "paper-figure"
    assert skill_orchestrator.render_owner(plan) == ""
    assert plan.as_dict()["execution_contract_issues"] == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("strategy,skill", [
    ("model_composed_full_svg", "model-svg-figure"),
    ("model_generated_image", "paper-illustration"),
])
def test_explicit_model_asset_retains_actual_model_execution_requirement(
    tmp_path: Path, strategy: str, skill: str,
) -> None:
    _write_specs(tmp_path, [_asset("model", strategy)])
    contract = resolve_execution_contract("figure", {}, project_path=tmp_path)
    assert contract.kind == "hybrid" and contract.policy_required
    assert contract.model_execution_mode == "any_component"
    plan = skill_orchestrator.select("figure", "/paper-figure", str(tmp_path), {})
    assert plan.primary == skill and plan.policy_required
    assert not plan.execution_contract_issues


def test_mixed_portfolio_requires_all_declared_model_asset_owners(tmp_path: Path) -> None:
    figures = [_asset("method", "deterministic_architecture"),
               _asset("illustration", "model_generated_image"),
               _asset("model_svg", "model_composed_full_svg")]
    _write_specs(tmp_path, figures)
    policy = resolve_figure_execution_policy(tmp_path)
    assert policy.kind == "hybrid" and policy.model_execution_mode == "any_component"
    assert policy.model_skills == ("paper-illustration", "model-svg-figure")
    assert [item["id"] for item in policy.assets] == [item["id"] for item in figures]


def test_explicit_legacy_glyph_declaration_remains_model_owned(tmp_path: Path) -> None:
    _write_specs(tmp_path, [{"id": "legacy", "kind": "figure", "producer_kind": "model",
                           "composition_owner": "glyph", "recommended_skill": "rich-svg-figure",
                           "recommended_backend": "rich_svg", "full_svg_authority": False}])
    policy = resolve_figure_execution_policy(tmp_path)
    assert policy.kind == "hybrid" and policy.policy_required
    assert policy.model_skills == ("rich-svg-figure",)


@pytest.mark.parametrize("defect", [
    "missing_producer", "missing_strategy", "unsupported", "wrong_owner", "wrong_skill",
    "wrong_authority", "duplicate", "empty", "schema", "policy_schema", "malformed_root",
])
def test_invalid_producer_contract_never_waives_model_requirement(tmp_path: Path, defect: str) -> None:
    figures = [_asset("method", "deterministic_architecture")]
    updates = {}
    if defect == "missing_producer":
        figures[0].pop("producer_kind")
    elif defect == "missing_strategy":
        figures[0].pop("production_strategy")
    elif defect == "unsupported":
        figures[0]["production_strategy"] = "unknown_renderer"
    elif defect == "wrong_owner":
        figures[0]["composition_owner"] = "model"
    elif defect == "wrong_skill":
        figures[0]["recommended_skill"] = "rich-svg-figure"
    elif defect == "wrong_authority":
        figures[0]["full_svg_authority"] = True
    elif defect == "duplicate":
        figures.append(copy.deepcopy(figures[0]))
    elif defect == "empty":
        figures.clear()
    elif defect == "schema":
        updates["schema"] = 3
    elif defect == "policy_schema":
        updates["production_policy_schema"] = 7
    path = _write_specs(tmp_path, figures, **updates)
    if defect == "malformed_root":
        path.write_text("[]", encoding="utf-8")
    before = path.read_bytes()
    contract = resolve_execution_contract("figure", {}, project_path=tmp_path)
    assert contract.kind == "hybrid" and contract.policy_required
    assert contract.blocking_issues
    assert contract.as_dict()["execution_contract_issues"] == list(contract.blocking_issues)
    assert path.read_bytes() == before


def test_missing_project_or_specs_remains_conservative(tmp_path: Path) -> None:
    assert resolve_execution_contract("figure").kind == "hybrid"
    contract = resolve_execution_contract("figure", project_path=tmp_path)
    assert contract.policy_required and contract.blocking_issues


@pytest.mark.parametrize("conflict", ["producer", "asset_set", "schema"])
def test_optional_plan_must_agree_with_canonical_spec(tmp_path: Path, conflict: str) -> None:
    figures = [_asset("method", "deterministic_architecture")]
    _write_specs(tmp_path, figures)
    assets = copy.deepcopy(figures)
    if conflict == "producer":
        assets[0]["producer_kind"] = "model"
    elif conflict == "asset_set":
        assets.append(_asset("another", "model_generated_image"))
    plan = {"schema": 1 if conflict == "schema" else 2, "assets": assets}
    path = tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    policy = resolve_figure_execution_policy(tmp_path)
    assert policy.issues and policy.policy_required and policy.kind == "hybrid"


def test_matching_optional_plan_does_not_change_declared_ownership(tmp_path: Path) -> None:
    figures = [_asset("protocol", "deterministic_template")]
    _write_specs(tmp_path, figures)
    (tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({"schema": 2, "assets": figures}), encoding="utf-8",
    )
    assert resolve_figure_execution_policy(tmp_path).kind == "runtime_owned"
