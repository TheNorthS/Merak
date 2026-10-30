"""Repeated launch preparation must not invalidate an unchanged paper budget."""

import json

from server.services.paper_budget import PaperBudgetService


def test_resume_preserves_unchanged_budget_bytes_and_timestamp(tmp_path):
    service = PaperBudgetService()
    service.prepare(tmp_path, 9, 1, "ICLR")
    path = tmp_path / service.budget_relative_path
    before, timestamp = path.read_bytes(), path.stat().st_mtime_ns
    service.prepare(tmp_path, 9, 1, "ICLR")
    assert path.read_bytes() == before and path.stat().st_mtime_ns == timestamp


def test_changed_length_or_policy_still_updates_budget_and_invalidates_acceptance(tmp_path):
    service = PaperBudgetService()
    service.prepare(tmp_path, 9, 1, "ICLR")
    path = tmp_path / service.budget_relative_path
    previous = path.read_bytes()
    service.prepare(tmp_path, 12, 1, "ICLR")
    assert path.read_bytes() != previous and json.loads(path.read_bytes())["target_pages"] == 12
    value = json.loads(path.read_bytes())
    value["policy"]["counting"] = "Altered counting policy"
    path.write_text(json.dumps(value))
    service.prepare(tmp_path, 12, 1, "ICLR")
    assert json.loads(path.read_bytes())["policy"]["counting"] != "Altered counting policy"
