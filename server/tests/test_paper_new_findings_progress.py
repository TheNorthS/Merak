"""Fresh author findings receive a first repair attempt without resolving untested prior checks."""

from types import SimpleNamespace
import pytest

from server.workflows.paper_revision_progress import new_author_scope
from server.workflows.revision_progress_diagnostics import measure_revision_progress


def test_new_consistency_stage_does_not_inherit_exhausted_preparation_counter():
    context = SimpleNamespace(revision_owner=SimpleNamespace(id="paper"), last_revision_execution_succeeded=True,
        last_revision_scope_before="old-freeze", scope_signature="new-authors",
        diagnostics={"findings":[{"category":"model_consistency","stage_id":"method",
                                   "target_files":["paper/sections/03_method.tex"]}]})
    progress = measure_revision_progress(current={"NEW_AUTHOR_FINDING"}, previous={"STALE_FREEZE"},
        scope_signature="new-authors", previous_scope_signature="old-freeze", previous_count=2,
        revision_started=True, transport_attempted=False, evaluation_complete=False,
        new_author_scope=new_author_scope(context))
    assert progress["consecutive_no_progress"] == 0
    assert progress["resolved_finding_ids"] == []
    assert progress["not_evaluated_finding_ids"] == ["STALE_FREEZE"]


def test_same_finding_or_uncompleted_execution_still_exhausts_budget():
    progress = measure_revision_progress(current={"SAME"}, previous={"SAME"}, scope_signature="after",
        previous_scope_signature="before", previous_count=1, revision_started=True, transport_attempted=False,
        new_author_scope=True)
    assert progress["consecutive_no_progress"] == 2
    context = SimpleNamespace(revision_owner=SimpleNamespace(id="paper"), last_revision_execution_succeeded=False)
    assert not new_author_scope(context)


@pytest.mark.parametrize("mutation", ["", "unowned", "wrong_operation", "same_scope", "same_findings"])
def test_new_review_can_mix_section_authors_with_a_deterministic_table_producer(mutation):
    runtime = {"id": "PAPER-RUNTIME-CONSISTENCY-table", "category": "publication_table",
        "stage_id": "assembly", "producer_kind": "deterministic", "owner_node": "paper",
        "runtime_operation": "refresh_paper_runtime_inputs", "legal_write_targets": [],
        "target_files": ["paper/tables/synthetic_preview_results.tex"]}
    if mutation == "unowned":
        runtime["producer_kind"] = ""
    if mutation == "wrong_operation":
        runtime["runtime_operation"] = "unknown"
    context = SimpleNamespace(revision_owner=SimpleNamespace(id="paper"), last_revision_execution_succeeded=True,
        last_revision_scope_before="literature", scope_signature="literature" if mutation == "same_scope" else "review",
        diagnostics={"findings": [{"category": "model_consistency", "stage_id": "method",
            "target_files": ["paper/sections/03_method.tex"]}, runtime]})
    progress = measure_revision_progress(current={"METHOD", "TABLE"},
        previous={"METHOD", "TABLE"} if mutation == "same_findings" else {"LITERATURE"},
        scope_signature=context.scope_signature, previous_scope_signature="literature", previous_count=1,
        revision_started=True, transport_attempted=False, evaluation_complete=False,
        new_author_scope=new_author_scope(context))
    assert progress["consecutive_no_progress"] == (2 if mutation else 0)
    assert progress["resolved_finding_ids"] == []
    if mutation != "same_findings":
        assert progress["not_evaluated_finding_ids"] == ["LITERATURE"]
