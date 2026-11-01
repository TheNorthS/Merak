"""Resume the interrupted repair transaction before inspecting its provisional outputs."""


def reopen_missing_source_review(state) -> None:
    """One explicit resume may rerun impact review with the newly supported source evidence."""
    from pathlib import Path
    from .report_revision_store import require_expected
    def update(saved):
        if saved.get('status') == 'completed':
            return
        for record in saved.get('report_revisions', {}).values():
            from .report_iteration_handoff import recover_joined_report_edits
            if recover_joined_report_edits(Path(state.project_path).resolve(), str(saved.get('run_id') or ''), record):
                continue
            from ..services.specialist_targeted_repair import reopen_specialist_review
            if reopen_specialist_review(Path(state.project_path).resolve(), saved, record):
                continue
            from .report_refresh_recovery import recover_plan_after_result_binding
            if recover_plan_after_result_binding(Path(state.project_path), saved, record):
                continue
            impact = record.get('impact', {})
            unresolved = impact.get('unresolved') or []
            if (record.get('status') == 'needs_attention' and not record.get('metadata_projection_review')
                    and impact.get('scope') in {'local', 'linked'} and unresolved
                    and all('literature/references.bib' in message for message in unresolved)
                    and not record.get('refresh_completed')):
                require_expected(Path(state.project_path), record)
                record.update(status='verifying', metadata_projection_review=1)
                continue
            if record.get('status') == 'needs_attention' and record.get('impact', {}).get('unresolved'):
                from .report_impact_followup import prepare_impact_followup, apply_followup_state
                options = saved.get('config', {}).get('options', {})
                if prepare_impact_followup(Path(state.project_path), record, options=options,
                                           maximum=int(options.get('max_revision_rounds') or 6)):
                    apply_followup_state(saved, record)
                    continue
            if (record.get('status') == 'needs_attention' and 'paper' in record.get('refresh_completed', [])
                    and 'paper_validation' not in record.get('refresh_completed', [])
                    and str(record.get('error', '')).startswith(('PaperAcceptanceError:', 'ValueError: Unrelated scientific inputs changed during local repair:'))):
                from .report_revision_impact import source_fingerprints
                require_expected(Path(state.project_path), record)
                current = source_fingerprints(Path(state.project_path))
                if current != record.get('refresh_snapshot'):
                    from .report_print_recovery import verified_print_refresh
                    if not verified_print_refresh(Path(state.project_path), record.get('refresh_snapshot') or {}, current):
                        raise ValueError('Paper changed outside the saved refresh checkpoint; reassess before continuing')
                    record['refresh_snapshot'] = current
                record.update(status='awaiting_review', resume_reason='Paper producer must resolve its current gate findings')
                continue
            if (record.get('status') == 'needs_attention' and not record.get('specialist_followup_version')
                    and str(record.get('error', '')).startswith('ValueError: Specialist remains invalid after bounded repair:')
                    and record.get('owner_scope_recovery_version') == 1):
                require_expected(Path(state.project_path), record)
                record.update(status='refreshing', specialist_followup_version=1)
                continue
            if (record.get('status') == 'needs_attention' and str(record.get('error', '')).startswith(
                    'ValueError: Specialist remains invalid after bounded repair:')):
                from ..services.specialist_targeted_repair import recover_blocked_specialist_write
                require_expected(Path(state.project_path), record)
                if recover_blocked_specialist_write(Path(state.project_path), record):
                    record['status'] = 'refreshing'
                    continue
            if (record.get('status') == 'needs_attention' and not record.get('specialist_repair_version')
                    and record.get('impact', {}).get('scope') in {'local', 'linked'}
                    and not record.get('impact', {}).get('unresolved')
                    and str(record.get('error', '')).startswith('ValueError: Specialist requires substantive revision:')):
                require_expected(Path(state.project_path), record)
                record.update(status='refreshing', specialist_repair_version=1)
                continue
            if (record.get('status') != 'needs_attention' or record.get('source_review_version') == 1
                    or record.get('impact', {}).get('scope') != 'local'
                    or not record.get('impact', {}).get('unresolved') or record.get('refresh_completed')
                    or not any(g['owner'] == 'lit' for g in record.get('groups', []))):
                continue
            require_expected(Path(state.project_path), record)
            record.setdefault('impact_history', []).append(record.get('impact', {}))
            record.update(status='verifying', source_review_version=1)
    state.update_state(update)


def active_report_consumer(saved: dict) -> str:
    active = [record for record in saved.get("report_revisions", {}).values()
              if record.get("status") in {"editing", "verifying", "refreshing", "interrupted"}]
    if len(active) > 1:
        raise ValueError("Multiple active report repair transactions")
    if not active:
        return ""
    record = active[0]
    if record.get("schema") != 1 or record.get("consumer") not in {"audit", "review"}:
        raise ValueError("Invalid persisted report repair transaction")
    return record["consumer"]


def protect_report_recovery(host, run, state) -> bool:
    """No accepted status is invented: only the repair consumer may execute until closure."""
    consumer = active_report_consumer(state.load() or {})
    if not consumer:
        return False
    node = next(node for node in host._get_default_nodes() if node.id == consumer)
    run.nodes = [node]
    return True
