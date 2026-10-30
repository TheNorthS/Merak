"""Independent tool reviewers cannot launch skills or write into a runtime directory."""

from types import SimpleNamespace

import pytest

from server.agent.reviewer_scope import bind_review_scope, review_root


def test_reviewer_receives_only_project_scoped_read_tools(tmp_path):
    session = SimpleNamespace(project_path=".", max_iterations=50)
    tools = bind_review_scope(session, review_root(str(tmp_path)), new_session=True)
    assert tools == ["Read", "Glob", "Grep"]
    assert session.project_path == str(tmp_path.resolve()) and session.allowed_write_paths == []
    assert session.tool_policy == "workflow_artifacts"
    assert session.max_iterations == 20


def test_reviewer_without_project_is_text_only_and_cross_project_reply_is_rejected(tmp_path):
    session = SimpleNamespace(project_path="", max_iterations=50)
    assert bind_review_scope(session, None) == []
    session.project_path = str(tmp_path / "different")
    with pytest.raises(ValueError, match="different project"):
        bind_review_scope(session, tmp_path)
