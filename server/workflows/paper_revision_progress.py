"""A newly reached independent manuscript review opens its own bounded author scope."""

from typing import Any


def _review_producer_finding(item: Any) -> bool:
    if not isinstance(item, dict) or not item.get("stage_id") or not item.get("target_files"):
        return False
    if item.get("category") == "model_consistency":
        return True
    return bool(str(item.get("id") or "").startswith("PAPER-RUNTIME-CONSISTENCY-")
        and item.get("category") == "publication_table" and item.get("stage_id") == "assembly"
        and item.get("owner_node") == "paper" and item.get("producer_kind") == "deterministic"
        and item.get("runtime_operation") == "refresh_paper_runtime_inputs"
        and item.get("legal_write_targets") == []
        and item.get("target_files") == ["paper/tables/synthetic_preview_results.tex"])


def new_author_scope(context: Any) -> bool:
    """Do not count first-time author findings as failed attempts at an earlier preparation error."""
    if context.revision_owner.id != "paper" or not context.last_revision_execution_succeeded:
        return False
    findings = context.diagnostics.get("findings") or []
    return bool(findings and all(_review_producer_finding(item) for item in findings)
        and context.last_revision_scope_before and context.scope_signature != context.last_revision_scope_before)
