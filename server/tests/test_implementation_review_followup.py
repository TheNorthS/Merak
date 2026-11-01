"""Reviews must close the actual repair loop, not replace old issues with new wording."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.implementation_review_completion import ImplementationReviewIncomplete
from server.services.implementation_review_followup import (
    review_followup_context, review_with_followup, validate_resolutions,
)


PRIOR = {"findings": [{"id": "source-revision", "scope": "implementation_correctness",
    "severity": "warning", "message": "Unregistered source revision", "target_files": ["src/provenance.py"]}]}


@pytest.mark.parametrize("result", [
    {"findings": []},
    {"findings": [{"id": "renamed-revision"}]},
    {"resolved_findings": [{"id": "source-revision", "evidence": []}]},
    {"resolved_findings": [{"id": "unknown", "evidence": ["src:check"]}]},
    {"findings": [{"id": "source-revision"}], "resolved_findings": [{"id": "source-revision", "evidence": ["src:check"]}]},
])
def test_omission_renaming_or_unsupported_resolution_cannot_count_as_progress(result):
    with pytest.raises(ImplementationReviewIncomplete):
        validate_resolutions(PRIOR, result)


def test_explicit_resolution_and_still_open_dispositions_are_preserved():
    validate_resolutions(PRIOR, {"findings": [{"id": "source-revision"}]})
    validate_resolutions(PRIOR, {"resolved_findings": [{"id": "source-revision",
        "evidence": ["src/provenance.py:persist now rejects missing source identity"]}]})


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [True, False])
async def test_missing_disposition_continues_reviewer_once_without_author_repair(resolved):
    prompts = []
    async def review(*args):
        prompts.append(review_followup_context.get())
        return json.dumps({"findings": [], "resolved_findings": [{"id": "source-revision",
            "evidence": ["src/provenance.py:persist rejects placeholder"]}]}) if resolved and len(prompts) == 2 else '{"findings": []}'
    host = SimpleNamespace(_run_code_review=review, _parse_training_check_result=lambda raw, **kw: json.loads(raw), _emit=AsyncMock())
    if resolved:
        _, result = await review_with_followup(host, object(), "general research", {}, "draft", PRIOR)
        assert result["resolved_findings"][0]["id"] == "source-revision"
    else:
        with pytest.raises(ImplementationReviewIncomplete):
            await review_with_followup(host, object(), "general research", {}, "draft", PRIOR)
    assert len(prompts) == 2 and "source-revision" in prompts[0]
    assert "Unaccounted prior finding IDs" in prompts[1]
    assert host._emit.await_count == 1
    assert review_followup_context.get() == ""


def test_training_parser_preserves_reviewer_resolution_evidence():
    from server.workflows.engine import WorkflowEngine
    resolution = [{"id": "source-revision", "evidence": ["src/provenance.py:persist rejects placeholder"]}]
    result = WorkflowEngine()._parse_training_check_result(json.dumps({
        "verdict": "PASS", "summary": "Verified source revision check", "findings": [], "resolved_findings": resolution,
    }), assurance="draft")
    assert result["resolved_findings"] == resolution
