"""Require persisted primary outputs before recording a model stage as complete.

This check owns delivery only. Scientific acceptance remains with the existing
node gates. One continuation uses the same transcript and remaining budgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..agent.engine import agent_engine
from ..contracts.registry import workflow_artifact_contracts
from ..contracts.writers import versioned_artifact_write_error
from ..services.method_contract import method_contract_service
from ..services.skill_registry import skill_registry
from .node_execution_context import NodeExecutionContext
from .node_execution_invocation import run_primary_session


MAX_COMPLETION_STEPS = 8
_RUNTIME_OUTPUTS = frozenset({"slides/main.pdf", "slides/SLIDE_BUILD.json"})


@dataclass(frozen=True)
class PrimaryOutputCheck:
    paths: tuple[Path, ...]
    issues: tuple[str, ...]


def primary_output_paths(context: NodeExecutionContext) -> tuple[Path, ...]:
    """Scope delivery to outputs declared by this skill and macro-stage owner."""
    metadata = skill_registry.get_skill(context.skill_plan.primary)
    contract = workflow_artifact_contracts.get(context.node.id)
    if metadata is None or contract is None:
        return ()
    canonical = {value.rstrip("/") for value in contract.required}
    root = Path(context.project_path).expanduser().resolve()
    paths = []
    for value in metadata.output_files:
        relative = str(value).rstrip("/")
        if relative not in canonical or relative in _RUNTIME_OUTPUTS:
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"primary output escapes project: {value}")
        paths.append(path)
    return tuple(dict.fromkeys(paths))


def inspect_primary_outputs(context: NodeExecutionContext) -> PrimaryOutputCheck:
    """Validate persisted delivery without running risk, model, or runtime gates."""
    paths = primary_output_paths(context)
    if not paths:
        return PrimaryOutputCheck((), ())
    _passed, issues = context.host._artifact_check(
        list(paths), project_path=context.project_path,
        baseline=None if context.revision_context else context.node.artifact_baseline or None,
        input_baseline=context.run.input_baseline,
    )
    issues = list(issues)
    if context.node.id == 'ppt':
        from ..services.slide_authoring_contract import talk_delivery_findings
        root = Path(context.project_path).resolve()
        main = root / 'slides/main.tex'
        text = main.read_text(encoding='utf-8-sig') if main.is_file() else ''
        issues.extend(item['message'] for item in talk_delivery_findings(root, text))
    invalid_contracts: set[Path] = set()
    for path in paths:
        if not path.is_file() or path.suffix.casefold() != ".json":
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            issues.append(f"{path.name}: cannot read primary output: {error}")
            invalid_contracts.add(path)
            continue
        error = versioned_artifact_write_error(context.project_path, path, content)
        if error:
            issues.append(error)
            invalid_contracts.add(path)
    selected = Path(context.project_path).resolve() / "ideas/SELECTED_IDEA.json"
    if selected in paths and selected.is_file() and selected not in invalid_contracts:
        _valid, contract_issues, _details = method_contract_service.validate_selected_idea(
            context.project_path,
        )
        issues.extend(contract_issues)
    return PrimaryOutputCheck(paths, tuple(dict.fromkeys(str(item) for item in issues)))


async def _completion_event(
    context: NodeExecutionContext, event: str, check: PrimaryOutputCheck,
) -> None:
    await context.host._emit(context.run, event, {
        "node_id": context.node.id, "session_id": context.session.id,
        "artifacts": [str(path) for path in check.paths],
        "issues": list(check.issues), "maximum_completion_steps": MAX_COMPLETION_STEPS,
        "completion_mode": context.completion_mode,
    })


def _completion_prompt(context: NodeExecutionContext, check: PrimaryOutputCheck) -> str:
    root = Path(context.project_path).resolve()
    outputs = "\n".join(f"- {path.relative_to(root).as_posix()}" for path in check.paths)
    defects = "\n".join(f"- {issue}" for issue in check.issues)
    return (
        "The last response ended before the primary output contract was satisfied. "
        "Continue this same task from the existing transcript. Use its completed "
        "searches and source evidence; finish only the current owner's outputs. "
        "A promise to write is not a saved artifact. Use Write/Edit, then Read to "
        "verify the files. Preserve accepted upstream and declared read-only inputs. "
        "Do not invent evidence or change scientific decisions to satisfy delivery.\n\n"
        f"Required primary outputs:\n{outputs}\n\nDelivery defects:\n{defects}"
    )


async def ensure_primary_output_delivery(context: NodeExecutionContext) -> None:
    """Attempt at most one same-session completion; incomplete output stays unaccepted."""
    if context.completion_mode != "normal":
        return
    if context.run.status in {"cancelled", "interrupted"}:
        return
    if getattr(context.session.status, "value", context.session.status) == "cancelled":
        return
    check = inspect_primary_outputs(context)
    if not check.issues:
        return
    maximum = context.session.max_iterations
    unsupported_schema = any("unsupported schema" in issue for issue in check.issues)
    if context.session.iterations < maximum and not unsupported_schema:
        await _completion_event(context, "node_primary_output_completion_started", check)
        context.session.max_iterations = min(
            maximum, context.session.iterations + MAX_COMPLETION_STEPS,
        )
        try:
            context.result = await run_primary_session(
                context, user_message=_completion_prompt(context, check),
                allow_text_fallback=False,
            )
        finally:
            context.session.max_iterations = maximum
            agent_engine._persist_session_transcript(context.session)
        check = inspect_primary_outputs(context)
    if check.issues:
        context.completion_mode = "artifact_incomplete"
        context.result = (
            context.result + "\n\nPrimary output delivery remains incomplete: "
            + "; ".join(check.issues)
        ).strip()
        await _completion_event(context, "node_primary_output_incomplete", check)
        raise RuntimeError("PRIMARY_OUTPUT_INCOMPLETE: " + "; ".join(check.issues))
    elif context.completion_mode == "normal":
        context.completion_mode = "artifact_completion_continuation"
        await _completion_event(context, "node_primary_output_completion_finished", check)
