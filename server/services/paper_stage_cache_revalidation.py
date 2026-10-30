"""Pure eligibility for fresh local review after validator-only cache invalidation."""

from __future__ import annotations

import re
from typing import Any

from .manuscript_text import read_owned_state, sha256


_AGGREGATE_PREFIX = "Staged manuscript did not satisfy the quality contract: "
AUTOMATIC_CONSISTENCY_DIRECTIVE = (
    "Reconcile all accepted sections after the directed repair; preserve unrelated valid content."
)


def freshness_only_issue(issue: str, stage_label: str) -> bool:
    """Only explicit cache-state findings can avoid a scientific author invocation."""
    text = str(issue).strip()
    if text.startswith(_AGGREGATE_PREFIX):
        text = text[len(_AGGREGATE_PREFIX):]
    label = re.escape(stage_label)
    return bool(re.fullmatch(
        rf"(?:staged-paper:\s*)?(?:{label}:\s*)?{label} (?:has not passed its local section contract\.?"
        r"|requires deterministic revalidation under the current paper (?:contract|validator)\.?)",
        text, re.IGNORECASE,
    ))


def stage_freshness_only(coordinator: Any, run: Any) -> bool:
    """Ignore exact same-stage routing selectors, never scientific feedback or foreign targets."""
    issues = run.revision_issues
    if not issues:
        return False
    root = coordinator.paths["root"].resolve()
    outputs = coordinator.service.stage_outputs(coordinator.paths, run.stage_id)
    owned = {path.resolve().relative_to(root).as_posix() for path in outputs}
    owned.add("paper/main.tex")
    label = coordinator.stage_labels.get(run.stage_id, run.stage_id)
    found = False
    for issue in issues:
        if isinstance(issue, str) and issue.startswith("Target artifact: "):
            if issue[len("Target artifact: "):] not in owned:
                return False
        elif freshness_only_issue(issue, label):
            found = True
        else:
            return False
    return found


def global_artifact_issue(issue: str) -> bool:
    """A main-document asset reference finding belongs to consistency, not every author."""
    return bool(re.match(
        r"^(?:staged-paper:\s*)?(?:scientific assets? (?:is |are )?included but never referenced in prose"
        r"|undefined references:|unknown citation keys:|main\.tex\b)", str(issue).strip(), re.IGNORECASE,
    ))


def bound_stage_content(coordinator: Any, run: Any) -> bool:
    """Require unchanged authored bytes, stage inputs and the actual scientific freeze."""
    return _bound_stage_identity(coordinator, run.stage_id, run.record) and scientific_context_current(coordinator)


def _bound_stage_identity(coordinator: Any, stage: str, record: dict[str, Any]) -> bool:
    service, paths = coordinator.service, coordinator.paths
    outputs = service.stage_outputs(paths, stage)
    recorded = record.get("output_hashes") or {}
    if (not outputs or set(recorded) != {path.name for path in outputs}
            or any(not path.is_file() or recorded.get(path.name) != sha256(path) for path in outputs)
            or record.get("input_signature") != service.stage_input_signature(paths, stage)):
        return False
    return True


def scientific_context_current(coordinator: Any) -> bool:
    """A local revalidation cannot rebind changed research sources or scientific options."""
    service, paths = coordinator.service, coordinator.paths
    state = read_owned_state(paths["state"])
    freeze = service.validate_scientific_freeze(coordinator.project_path, coordinator.options)
    return bool(freeze.get("passed") and state.get("scientific_freeze_id") == freeze.get("freeze_id")
                and state.get("authoring_inputs") == service.authoring_input_hashes(coordinator.project_path)
                and state.get("authoring_signature") == service.authoring_signature(coordinator.project_path, coordinator.options))


def automatic_consistency_revalidation(coordinator: Any, run: Any) -> bool:
    """Re-review the current report only after genuine cache-only author revalidation.

    The report may contain a prior authorized write awaiting local review. Its
    current content must pass the caller's fresh consistency gate; an old report
    hash or PASS cannot certify it. Authored research bytes remain strictly bound.
    """
    original = list(coordinator.revision_issues or [])
    authors = [stage for stage in coordinator.author_order if stage != "consistency"]
    if (run.stage_id != "consistency" or not coordinator.automatic_consistency_revalidation
            or not original or run.revision_issues != [AUTOMATIC_CONSISTENCY_DIRECTIVE, *original]
            or run.prior_attempts < 1
            or run.record.get("input_signature") != coordinator.service.stage_input_signature(coordinator.paths, "consistency")
            or not _author_freshness_request(coordinator, original, authors)
            or not scientific_context_current(coordinator)):
        return False
    state = read_owned_state(coordinator.paths["state"])
    for stage in authors:
        record = dict(state.get("stages", {}).get(stage) or {})
        if (not coordinator.service.stage_is_current(coordinator.paths, state, stage)
                or not _bound_stage_identity(coordinator, stage, record)
                or not coordinator.service.validate_stage(coordinator.project_path, stage).get("passed")):
            return False
    return True


def _author_freshness_request(coordinator: Any, issues: list[str], authors: list[str]) -> bool:
    root = coordinator.paths["root"].resolve()
    owned = {path.resolve().relative_to(root).as_posix() for stage in authors
             for path in coordinator.service.stage_outputs(coordinator.paths, stage)}
    owned.add("paper/main.tex")
    found = False
    for issue in issues:
        if isinstance(issue, str) and issue.startswith("Target artifact: "):
            if issue[len("Target artifact: "):] not in owned:
                return False
        elif any(freshness_only_issue(issue, coordinator.stage_labels.get(stage, stage)) for stage in authors):
            found = True
        else:
            return False
    return found
