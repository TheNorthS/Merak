"""A validator repair can accept saved text without model replay or losing conflicts."""

import json
from types import SimpleNamespace
import pytest

from server.agent.tools.file_tools import file_write
from server.services.manuscript_text import read_text
from server.services.paper_candidate_transaction import PaperCandidate
from server.services.paper_candidate_revalidation import revalidate_saved_candidate


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["validator", "inputs", "canonical", "candidate_tampered", "still_invalid", "new_review"])
async def test_saved_candidate_is_revalidated_only_with_matching_science_and_baseline(tmp_path, change):
    root = tmp_path.resolve()
    target = root / "paper/sections/01_introduction.tex"
    payload = {"authoring": {"method": "original"}, "upstream": "original", "validator": "old"}
    with PaperCandidate(root, "introduction", [target], lambda: json.dumps(payload, sort_keys=True)) as candidate:
        await file_write(str(target), "Two independently falsifiable contributions.")
    candidate.publish({"passed": False, "issues": ["old validator false negative"]})
    original_candidate = candidate.files[target].read_bytes()
    payload["validator"] = "fixed"
    if change == "inputs":
        payload["authoring"]["method"] = "changed"
    elif change == "canonical":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("User edit", encoding="utf-8")
    elif change == "candidate_tampered":
        candidate.files[target].write_text("Unrecorded candidate edit", encoding="utf-8")
    elif change == "new_review":
        payload["validator"] = "old"
    marks, reviews = [], []

    def validate(project, stage):
        assert read_text(target) == original_candidate.decode()
        return {"passed": change != "still_invalid", "issues": [] if change != "still_invalid" else ["real defect"]}

    service = SimpleNamespace(authoring_input_hashes=lambda p: payload["authoring"],
        stage_input_signature=lambda p, s: payload["upstream"], stage_validator_signature=lambda s: payload["validator"],
        stage_outputs=lambda p, s: [target], validate_stage=validate,
        mark_stage=lambda *a, **k: marks.append(k), record_review=lambda *a: reviews.append(a))
    coordinator = SimpleNamespace(service=service, paths={"root": root}, project_path=root)
    run = SimpleNamespace(stage_id="introduction", prior_attempts=6, review={},
                          revision_issues=["New reviewer correction"] if change == "new_review" else [])
    assert revalidate_saved_candidate(coordinator, run) is (change == "validator")
    if change == "validator":
        assert target.read_bytes() == original_candidate and marks[0]["attempt"] == 6
    elif change == "canonical":
        assert target.read_text() == "User edit" and not marks
    else:
        assert not target.exists() and not marks
