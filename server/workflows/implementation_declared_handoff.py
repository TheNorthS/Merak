"""Send newly declared integration defects to their actual source owner."""

from ..services.implementation_readiness_checks import readiness_findings
from ..services.implementation_review_receipt import pending_stage_obligations


def bind_declared_owner_handoff(context, state, report: dict) -> dict:
    """Keep integration writes narrow; a declaration cannot mark its owner repaired."""
    if state.stage.id != 'integration' or report.get('passed'):
        return report
    findings = readiness_findings(context.root, context.service._run_spec(context.root))
    owners = list(report.get('owner_reconciliation_required') or [])
    for stage in context.stages:
        if stage.id == 'integration':
            continue
        declared = [row for row in findings if row.get('stage_id') == stage.id
                    and set(row.get('target_files') or []).intersection(stage.targets)]
        if declared and pending_stage_obligations(context.service, context.root, stage.id,
                                                 context.direction, list(stage.targets)):
            owners.append(stage.id)
    return {**report, 'owner_reconciliation_required': list(dict.fromkeys(owners))}
