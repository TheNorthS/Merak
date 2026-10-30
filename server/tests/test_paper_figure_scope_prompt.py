"""Generic visible-figure instructions and cache contracts, using local fixtures only."""

from __future__ import annotations

import copy
import json

import pytest

from server.services import paper_draft_state
from server.services.paper_draft_preparation import _reuse_decision
from server.services.paper_draft_stages import _authoring_figures
from server.services.paper_drafting import AUTHOR_STAGE_ORDER, SECTION_BY_ID, PaperDraftingService
from server.services.paper_stage_prompts import build_stage_prompt


def _asset():
    return {"id": "source-bound-detail", "source_path": "figures/diagrams/detail.json", "source_sha256": "a" * 64,
        "output_path": "figures/diagrams/detail.pdf", "metadata": {"scientific_role": "method",
            "label": "fig:local-detail", "caption": "Internal source-defined interaction.",
            "source_data": ["experiments/registered-plan.md"],
            "scientific_scene": {"objects": [{"id": "unshown-full-scene-object"}]},
            "scientific_question": "Broader question includes an operation not in the detail",
            "architecture_compiler": {"covered_component_ids": ["input", "interaction"],
                "excluded_component_ids": ["holdout"], "rendered_node_count": 2, "rendered_relation_count": 1,
                "panel_contracts": [{"full_internal_contract": "not authoring scope"}]}}}


def test_authoring_assets_keep_original_rows_and_explicit_source_and_compact_scope():
    asset = _asset()
    before = copy.deepcopy(asset)
    row, = _authoring_figures({"figures": [asset]})
    assert row["scientific_role"] == "method" and row["label"] == "fig:local-detail"
    assert row["caption"] == asset["metadata"]["caption"] and row["output_path"] == asset["output_path"]
    assert row["source_data"] == asset["metadata"]["source_data"]
    assert row["source_path"] == asset["source_path"] and row["source_sha256"] == "a" * 64
    assert row["visible_scope"] == {"covered_component_ids": ["input", "interaction"],
        "excluded_component_ids": ["holdout"], "rendered_node_count": 2, "rendered_relation_count": 1}
    assert "unshown-full-scene-object" not in json.dumps(row) and "full_internal_contract" not in json.dumps(row)
    assert "scientific_question" not in row and asset == before
    row["visible_scope"]["covered_component_ids"].append("independent output")
    assert asset == before


def test_missing_source_proof_and_noncompiler_svg_scope_remain_explicitly_absent():
    asset = _asset()
    asset.pop("source_path")
    asset.pop("source_sha256")
    asset["metadata"].pop("architecture_compiler")
    row, = _authoring_figures({"figures": [asset]})
    assert row["source_path"] == row["source_sha256"] == "" and row["visible_scope"] == {}


@pytest.mark.parametrize("defect", ["bool_count", "negative_count", "excess_count", "missing_count", "wrong_list",
    "empty_id", "duplicate", "overlap", "wrong_size", "long_list", "bad_source_type"])
def test_malformed_scope_fails_instead_of_guessing_truncating_or_using_full_scene(defect):
    asset = _asset()
    scope = asset["metadata"]["architecture_compiler"]
    if defect == "bool_count": scope["rendered_node_count"] = True
    elif defect == "negative_count": scope["rendered_relation_count"] = -1
    elif defect == "excess_count": scope["rendered_relation_count"] = 1025
    elif defect == "missing_count": scope.pop("rendered_relation_count")
    elif defect == "wrong_list": scope["covered_component_ids"] = "input"
    elif defect == "empty_id": scope["covered_component_ids"][0] = ""
    elif defect == "duplicate": scope["covered_component_ids"] = ["input", "input"]
    elif defect == "overlap": scope["excluded_component_ids"] = ["input"]
    elif defect == "wrong_size": scope["rendered_node_count"] = 1
    elif defect == "long_list": scope["excluded_component_ids"] = [str(index) for index in range(257)]
    else: asset["source_path"] = {"guessed": "not a path"}
    with pytest.raises(ValueError):
        _authoring_figures({"figures": [asset]})


@pytest.mark.parametrize("stage", ["method", "experiments"])
def test_actual_bounded_prompts_do_not_attribute_full_science_or_fixed_operations_to_figures(tmp_path, stage):
    paths = paper_draft_state.drafting_paths(tmp_path)
    options = {"node_inputs": {"scope": "Keep the complete registered science separately from the diagram."}}
    prompt = build_stage_prompt(paths=paths, stage_id=stage, options=options, revision_issues=None,
        section_by_id=SECTION_BY_ID, author_order=AUTHOR_STAGE_ORDER,
        inventory=lambda *_args: "- paper/AUTHORING_ASSETS.json",
        write_assets=lambda _root, target, **_kwargs: target)
    assert "source_path (JSON/SVG or other declared source)" in prompt
    assert "actually visible in that" in prompt and "full method contract is not" in prompt
    assert "preserve the\nremaining scientific operations in separate equations or prose" in prompt
    assert "internal component IDs" in prompt and "must not appear in public prose" in prompt
    assert "Keep the complete registered science separately" in prompt
    assert "as data, split, shift, endpoint" not in prompt
    assert "128" not in prompt and "CSFS" not in prompt and "CBraMod" not in prompt


@pytest.mark.parametrize("fallback", ["source_signature", "authoring_signature", "identical_inputs", "literature_only"])
@pytest.mark.parametrize("version", [None, 0, True, "1"])
def test_old_figure_unaware_cache_cannot_use_any_signature_or_input_fallback(fallback, version):
    current = paper_draft_state.signature_options({"node_inputs": {"scope": "unchanged"}})
    old = {**current, "figure_scope_prompt_version": version}
    previous = {"schema_version": 3, "authoring_options": old, "authoring_inputs": {"literature/survey.md": "old"},
        "source_signature": "same" if fallback == "source_signature" else "old-source",
        "authoring_signature": "same" if fallback == "authoring_signature" else "old-author",
        "stages": {"method": {"status": "completed"}, "experiments": {"status": "completed"}}}
    inputs = {"literature/survey.md": "new" if fallback == "literature_only" else "old"}
    assert _reuse_decision(previous, "same", "same", inputs, current, 3)["reusable"] is False


def test_current_figure_scope_version_is_idempotent_and_keeps_unchanged_cache():
    current = paper_draft_state.signature_options({"node_inputs": {"scope": "registered"}})
    assert current["figure_scope_prompt_version"] == paper_draft_state.FIGURE_SCOPE_PROMPT_VERSION
    assert paper_draft_state.signature_options(current) == current
    assert paper_draft_state.gate_signature_options({}, current) == current
    previous = {"schema_version": 3, "authoring_options": current, "authoring_inputs": {},
                "source_signature": "same", "authoring_signature": "same"}
    assert _reuse_decision(previous, "same", "same", {}, current, 3)["reusable"] is True


def test_normal_prepare_archives_unaware_completed_sections_without_resigning_or_changing_science(tmp_path):
    from server.tests._staged_paper_drafting_support import seed_project

    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {"node_inputs": {"scope": "Keep all source science; explain only visible diagram scope."}}
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    originals = {}
    for stage, filename in (("method", "03_method.tex"), ("experiments", "04_experiments.tex")):
        target = paths["sections"] / filename
        target.write_text("Old authored figure claim requires normal re-authoring.", encoding="utf-8")
        originals[filename] = target.read_bytes()
        service.mark_stage(paths, stage, "completed", attempt=1, review={"passed": True, "issues": []})
    previous = json.loads(paths["state"].read_text(encoding="utf-8"))
    previous["authoring_options"].pop("figure_scope_prompt_version")
    paths["state"].write_text(json.dumps(previous), encoding="utf-8")
    science = {p: p.read_bytes() for p in service.authoring_source_paths(tmp_path) if p.is_file()}
    state = service.prepare(tmp_path, options)
    for stage, filename in (("method", "03_method.tex"), ("experiments", "04_experiments.tex")):
        assert state["stages"][stage]["status"] == "pending" and not (paths["sections"] / filename).exists()
        archived = list((paths["paper"] / "revisions").rglob(filename))
        assert len(archived) == 1 and archived[0].read_bytes() == originals[filename]
    assert all(p.read_bytes() == content for p, content in science.items())
    assert not list((tmp_path / ".merak").glob("skill-invocations/*.json"))


@pytest.mark.asyncio
async def test_genuine_native_compiler_scope_and_json_source_survive_authoring_projection(tmp_path):
    from server.tests.test_paper_figurespec_source import _native

    entry = await _native(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    row, = _authoring_figures({"figures": [entry]})
    assert row["source_path"] == entry["source_path"] and row["source_path"].endswith(".json")
    assert row["source_sha256"] == entry["source_sha256"]
    native = json.loads((tmp_path / entry["source_path"]).read_text(encoding="utf-8"))
    assert row["visible_scope"]["covered_component_ids"] == [node["id"] for node in native["nodes"]]
    assert row["visible_scope"]["rendered_relation_count"] == len(native["edges"])
    assert all(p.read_bytes() == content for p, content in before.items())
