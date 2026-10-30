"""Invalid JSON/schema receives bounded model repair while genuine failures remain failures."""

import json
from types import SimpleNamespace

import pytest

from server.services.review_response_repair import structured_review_response


@pytest.mark.asyncio
async def test_invalid_response_is_archived_and_retried_once_with_original_deadline(tmp_path):
    calls, bound = [], []
    responses = ['{"verdict":"FAIL",}', '{"verdict":"FAIL","issues":["Contradictory number"]}']
    async def call(prompt, remaining):
        calls.append((prompt, remaining))
        return SimpleNamespace(content=responses[len(calls)-1])
    async def activity():
        return None
    response, result = await structured_review_response(call=call, parse=lambda r: json.dumps(json.loads(r.content)),
        prompt="Frozen evidence and schema", timeout=90, directory=tmp_path,
        bind_prompt=bound.append, activity=activity)
    assert json.loads(result)["verdict"] == "FAIL"
    assert len(calls) == 2 and calls[1][1] <= calls[0][1]
    assert "Do not weaken findings" in bound[-1]
    assert (tmp_path / "attempt-1-response.txt").read_text() == responses[0]
    assert (tmp_path / "attempt-2-response.txt").read_text() == response.content


@pytest.mark.asyncio
async def test_two_invalid_responses_still_fail_without_synthetic_verdict(tmp_path):
    calls = []
    async def call(prompt, remaining):
        calls.append(prompt)
        return SimpleNamespace(content="invalid JSON")
    async def activity():
        return None
    with pytest.raises(json.JSONDecodeError):
        await structured_review_response(call=call, parse=lambda r: json.loads(r.content), prompt="evidence",
            timeout=90, directory=tmp_path, bind_prompt=lambda _:None, activity=activity)
    assert len(calls) == 2
