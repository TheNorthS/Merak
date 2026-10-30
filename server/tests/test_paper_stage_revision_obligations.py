"""A local section failure cannot hide its routed scientific repair obligations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.services.paper_draft_coordinator import DraftCoordinator, StageRun
from server.services.paper_draft_state import drafting_paths
from server.services.paper_draft_stages import revision_target_paths, stage_for_target, stage_outputs
from server.services.paper_drafting import AUTHOR_STAGE_ORDER, PAPER_STAGE_ORDER, PAPER_STAGE_LABELS, SECTION_BY_ID, SECTION_SPECS
from server.services.paper_stage_prompts import build_stage_prompt
from server.services.paper_stage_validation import invocation_contract


LOCAL_WORD_COUNT = "section too short (999; minimum 1000)"
METHOD_OBLIGATION = (
    "Method must cite and explain the included core-mechanism figure in prose: "
    "paper/sections/03_method.tex requires \\ref{fig:core-mechanism}."
)
METHOD_TARGET = "Target artifact: paper/sections/03_method.tex"
EXPERIMENTS_OBLIGATION = "Repair the evaluation-figure interpretation in paper/sections/04_experiments.tex."


def _coordinator(root):
    paths, prompt_calls, invoked = drafting_paths(root), [], []

    def prompt(project, stage, options, revision_issues):
        assert project == root
        prompt_calls.append((stage, list(revision_issues)))
        return build_stage_prompt(paths=paths, stage_id=stage, options=options,
            revision_issues=revision_issues, section_by_id=SECTION_BY_ID, author_order=AUTHOR_STAGE_ORDER,
            inventory=lambda _paths, _root: "- (none)",
            write_assets=lambda _root, target, **_keywords: target)

    async def invoke(stage, authored_prompt, contract):
        invoked.append((stage, authored_prompt, contract))
        return "Local fake-author response; no model or workflow is executed."

    service = SimpleNamespace(build_stage_prompt=prompt,
        stage_write_targets=lambda _paths, stage: stage_outputs(_paths, stage, SECTION_BY_ID),
        stage_target_semantic_signature=lambda *_arguments: "unchanged-fixture-input",
        invocation_contract=invocation_contract, revision_target_paths=revision_target_paths,
        stage_for_project_relative_target=lambda target: stage_for_target(target, SECTION_SPECS))
    coordinator = DraftCoordinator(service=service, project_path=root, direction="Local obligation regression",
        options={}, invoke_stage=invoke, emit=None, revision_issues=[], paths=paths,
        author_order=AUTHOR_STAGE_ORDER, paper_stage_order=PAPER_STAGE_ORDER,
        section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
        error_factory=lambda _stage, _issues: RuntimeError("Unexpected local test failure"),
        directed_repair_attempts=2, semantic_stall_attempts=2)
    return coordinator, prompt_calls, invoked


def _run(local, directed):
    return StageRun("method", {}, list(directed), 1, "directed-fixture" if directed else "",
                    bool(directed), 0, {"passed": False, "issues": list(local)})


@pytest.mark.asyncio
async def test_actual_stage_prompt_keeps_word_count_and_unresolved_core_reference_obligation(tmp_path):
    coordinator, calls, invoked = _coordinator(tmp_path)
    run = _run([LOCAL_WORD_COUNT], [METHOD_OBLIGATION, METHOD_TARGET])
    result = await coordinator._invoke(run, 2, 1, False)
    assert calls == [("method", [LOCAL_WORD_COUNT, METHOD_OBLIGATION, METHOD_TARGET])]
    assert len(invoked) == 1 and result.startswith("Local fake-author")
    assert all(issue in invoked[0][1] for issue in (LOCAL_WORD_COUNT, METHOD_OBLIGATION, METHOD_TARGET))
    assert "03_method.tex" in invoked[0][2] and "04_experiments.tex" not in invoked[0][2]
    assert run.review == {"passed": False, "issues": [LOCAL_WORD_COUNT]}
    assert run.revision_issues == [METHOD_OBLIGATION, METHOD_TARGET]


@pytest.mark.asyncio
async def test_feedback_is_exactly_deduplicated_in_local_then_directed_order(tmp_path):
    coordinator, calls, _invoked = _coordinator(tmp_path)
    run = _run([LOCAL_WORD_COUNT, METHOD_OBLIGATION, LOCAL_WORD_COUNT],
               [METHOD_OBLIGATION, METHOD_TARGET, METHOD_TARGET])
    await coordinator._invoke(run, 2, 1, False)
    assert calls == [("method", [LOCAL_WORD_COUNT, METHOD_OBLIGATION, METHOD_TARGET])]


@pytest.mark.asyncio
async def test_real_stage_routing_does_not_mix_sibling_author_obligations(tmp_path):
    coordinator, calls, invoked = _coordinator(tmp_path)
    coordinator.revision_issues = [METHOD_OBLIGATION, METHOD_TARGET, EXPERIMENTS_OBLIGATION]
    routed = coordinator._issues_by_stage(["method", "experiments"], coordinator.revision_issues)
    assert routed["method"] == [METHOD_OBLIGATION, METHOD_TARGET]
    assert routed["experiments"] == [EXPERIMENTS_OBLIGATION]
    await coordinator._invoke(_run([LOCAL_WORD_COUNT], routed["method"]), 2, 1, False)
    assert calls[0][1] == [LOCAL_WORD_COUNT, METHOD_OBLIGATION, METHOD_TARGET]
    assert EXPERIMENTS_OBLIGATION not in invoked[0][1]
    assert "Target artifact: paper/sections/04_experiments.tex" not in invoked[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("local,directed,expected", [
    ([LOCAL_WORD_COUNT], [], [LOCAL_WORD_COUNT]),
    ([], [METHOD_OBLIGATION, METHOD_TARGET], [METHOD_OBLIGATION, METHOD_TARGET]),
    ([], [], []),
])
async def test_no_directed_or_no_local_feedback_keeps_the_existing_prompt_behavior(tmp_path, local, directed, expected):
    coordinator, calls, _invoked = _coordinator(tmp_path)
    await coordinator._invoke(_run(local, directed), 2, 1, False)
    assert calls == [("method", expected)]


@pytest.mark.asyncio
async def test_no_progress_instruction_precedes_both_scoped_feedback_sources(tmp_path):
    coordinator, calls, _invoked = _coordinator(tmp_path)
    await coordinator._invoke(_run([LOCAL_WORD_COUNT], [METHOD_OBLIGATION]), 2, 1, True)
    assert calls[0][1][0].startswith("The immediately preceding invocation returned without changing")
    assert calls[0][1][1:] == [LOCAL_WORD_COUNT, METHOD_OBLIGATION]
