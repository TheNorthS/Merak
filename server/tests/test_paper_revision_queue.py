"""A sibling author failure must not lose the remaining scientific repairs."""

import hashlib
import pytest

from server.services.manuscript_text import read_owned_state, write_json
from server.services.paper_revision_queue import pending_author_repairs
from server.tests.test_paper_stage_revision_obligations import (
    _coordinator, METHOD_OBLIGATION, EXPERIMENTS_OBLIGATION,
)


def coordinator(root, issues):
    value, _calls, _invoked = _coordinator(root)
    value.revision_issues = issues
    value.service.validate_complete_draft = lambda *_args, **_kwargs: {"findings": []}
    value.service.directed_issue_signature = lambda items: hashlib.sha256(str(items).encode()).hexdigest()
    return value


@pytest.mark.asyncio
async def test_author_failure_and_restart_preserve_unvisited_scientific_repairs(tmp_path, monkeypatch):
    first = coordinator(tmp_path, [METHOD_OBLIGATION, EXPERIMENTS_OBLIGATION])
    write_json(first.paths["state"], {"stages": {}})
    first._configure_targeted_repairs()

    async def no_reuse(*_args):
        return False

    async def no_recovery(*_args):
        return None

    async def interrupted(*_args):
        raise TimeoutError("author connection interrupted")

    monkeypatch.setattr(type(first), "_reuse_if_current", no_reuse)
    monkeypatch.setattr(type(first), "_revalidate_without_invocation", no_reuse)
    monkeypatch.setattr(type(first), "_recover_interrupted_run", no_recovery)
    monkeypatch.setattr(type(first), "_defer_consistency_to_section_authors", lambda *_args: None)
    monkeypatch.setattr(type(first), "_attempt_stage", interrupted)
    with pytest.raises(TimeoutError):
        await first._run_stage("method")
    pending = pending_author_repairs(first.paths["state"], first.author_order)
    assert METHOD_OBLIGATION in pending and EXPERIMENTS_OBLIGATION in pending

    # A new process receives only the last local failure. The unvisited sibling
    # must remain directed even though the next global review is now stale.
    resumed = coordinator(tmp_path, ["Target artifact: paper/sections/03_method.tex"])
    resumed._configure_targeted_repairs()
    assert EXPERIMENTS_OBLIGATION in resumed.target_stage_issues["experiments"]
    assert METHOD_OBLIGATION in resumed.target_stage_issues["method"]

    async def successful(_self, run, _remaining):
        run.review = {"passed": True}

    monkeypatch.setattr(type(first), "_attempt_stage", successful)
    await resumed._run_stage("method")
    pending = pending_author_repairs(first.paths["state"], first.author_order)
    assert METHOD_OBLIGATION not in pending and EXPERIMENTS_OBLIGATION in pending
    await resumed._run_stage("experiments")
    assert pending_author_repairs(first.paths["state"], first.author_order) == []
    assert not read_owned_state(first.paths["state"]).get("review_passed")


def test_queue_never_reuses_an_independent_verdict_or_unowned_stage(tmp_path):
    value = coordinator(tmp_path, [])
    write_json(value.paths["state"], {"stages": {
        "method": {"pending_revision_issues": [METHOD_OBLIGATION, METHOD_OBLIGATION]},
        "consistency": {"pending_revision_issues": ["Old model PASS"]},
        "foreign": {"pending_revision_issues": ["Write a different artifact"]},
    }})
    assert pending_author_repairs(value.paths["state"], value.author_order) == [METHOD_OBLIGATION]
