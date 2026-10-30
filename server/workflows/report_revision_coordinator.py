"""A single bounded report repair cycle, followed by ordinary independent final gates."""

from pathlib import Path

from .revision_loop_context import RevisionComplete
from .report_revision_plan import report_revision_plan
from .report_revision_store import begin_report, save_report, require_expected, fingerprints


async def resume_report_revision(ctx) -> None:
    records = (ctx.run_state.load() or {}).get("report_revisions", {})
    from .report_impact_followup import prepare_impact_followup, save_impact_followup
    for record in records.values():
        if record.get('consumer') == ctx.node.id and record.get('status') == 'needs_attention':
            if prepare_impact_followup(Path(ctx.run.project_path).resolve(), record,
                                       options=ctx.opts, maximum=ctx.max_revision_rounds):
                save_impact_followup(ctx.run_state, record)
    active = [r for r in records.values() if r.get("consumer") == ctx.node.id
              and r.get("status") in {"editing", "verifying", "refreshing", "interrupted"}]
    if len(active) > 1:
        raise ValueError("Multiple active report revisions require reconciliation")
    if active:
        await _execute_report(ctx, active[0])


async def handle_report_revision(ctx) -> None:
    """Intercept eligible reports before the legacy one-owner restart loop."""
    if ctx.gate.get("accepted") or ctx.preparation_error:
        return
    root = Path(ctx.run.project_path).resolve()
    plan = report_revision_plan(root, ctx.node.id, ctx.diagnostics.get("findings", []), options=ctx.opts)
    if plan is None:
        return
    try:
        record = begin_report(ctx.run_state, plan, root, ctx.max_revision_rounds)
    except ValueError as error:
        await _wait(ctx, None, str(error))
        return
    await ctx.host._emit(ctx.run, "report_revision_started", {"node_id": ctx.node.id,
        "report_id": record["id"], "round": record["round"], "targets": record["targets"],
        "affected_nodes": sorted({g["owner"] for g in record["groups"]} | {"paper", "review", "audit", "compile", "ppt"}),
        "message": "集中处理本次报告的问题；历史阶段保留，相关交付待复核。"})
    await _execute_report(ctx, record)


async def _execute_report(ctx, record: dict) -> None:
    from .report_revision_execution import refresh_report_outputs
    root = Path(ctx.run.project_path).resolve()
    try:
        require_expected(root, record)
        await _author_and_verify(ctx, record, root)
        await refresh_report_outputs(ctx, record)
    except RevisionComplete:
        raise
    except Exception as error:
        from .report_revision_transport import transient_transport
        await _wait(ctx, record, f"{type(error).__name__}: {error}", transport=transient_transport(error))
    record["status"] = "awaiting_review"
    record["expected"] = fingerprints(root, record["targets"])
    save_report(ctx.run_state, record)
    ctx.host._refresh_run_nodes_from_state(ctx.run, ctx.run_state)
    await ctx.host._emit(ctx.run, "report_revision_verifying", {"node_id": ctx.node.id,
        "report_id": record["id"], "scope": record["scope"], "message": "定向修改已完成，独立审稿和审计待复核。"})
    raise RevisionComplete(({"accepted": False, "restart_required": True,
        "restart_from_node": "review", "reason": "report repairs complete; independent verification required"}, ctx.result))


async def _author_and_verify(ctx, record: dict, root: Path) -> None:
    from .report_revision_impact import capture_before, assess_impact
    from .report_revision_execution import edit_report_sources
    from .report_impact_followup import prepare_impact_followup, save_impact_followup
    while record['status'] != 'refreshing':
        if not record.get('before_path'):
            capture_before(root, record)
            save_report(ctx.run_state, record)
        await edit_report_sources(ctx, record)
        record['status'] = 'verifying'
        save_report(ctx.run_state, record)
        async def activity():
            await ctx.host._emit(ctx.run, 'report_revision_progress', {
                'node_id': ctx.node.id, 'report_id': record['id'], 'status': 'impact_review'})
        impact = await assess_impact(root, record, activity)
        record.update(impact=impact, scope=impact['scope'])
        save_report(ctx.run_state, record)
        if impact['scope'] in {'research', 'uncertain'} or impact['unresolved']:
            if prepare_impact_followup(root, record, options=ctx.opts, maximum=ctx.max_revision_rounds):
                save_impact_followup(ctx.run_state, record)
                continue
            await _wait(ctx, record, impact['reason'] + '; ' + '; '.join(impact['unresolved']))
        record['status'] = 'refreshing'
        save_report(ctx.run_state, record)


async def _wait(ctx, record: dict | None, reason: str, *, transport: bool = False) -> None:
    if record is not None:
        if transport:
            record['resume_stage'] = record['status']
            record['transport_interruptions'] = int(record.get('transport_interruptions', 0)) + 1
        record.update(status='interrupted' if transport and record['transport_interruptions'] < 3 else 'needs_attention', error=reason)
        save_report(ctx.run_state, record)
    gate = {"accepted": False, "waiting": True, "reason": "report revision requires reassessment",
        "summary": reason, "issues": [reason], "requires_human_decision": not transport,
        'intervention_kind': 'platform_repair' if transport else 'researcher_decision',
        'transport_exhausted': transport, 'error_category': 'transport' if transport else 'revision'}
    ctx.run_state.set_revision_waiting(ctx.node.id, round_number=record["round"] if record else ctx.max_revision_rounds,
        cycle=ctx.cycle, gate=gate, artifact_owner_id=ctx.node.id,
        artifact_signature=ctx.host._revision_artifact_signature(ctx.run.project_path, ctx.node.id, ctx.opts),
        runtime_signature=ctx.host._revision_runtime_signature(ctx.run.project_path, ctx.node.id, ctx.opts))
    await ctx.host._emit(ctx.run, "report_revision_waiting", {"node_id": ctx.node.id, "message": reason})
    await ctx.host._emit(ctx.run, "node_revision_waiting", {"node_id": ctx.node.id, **gate,
        "round": record["round"] if record else ctx.max_revision_rounds})
    raise RevisionComplete((gate, ctx.result))
