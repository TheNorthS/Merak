"""One bounded owner edit for a rejected specialist document, never an experiment rerun."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import time


def recover_blocked_specialist_write(root: Path, record: dict) -> bool:
    """Recover once after the exact ownership defect, only if the rejected edit changed nothing."""
    if record.get('owner_scope_recovery_version') == 1:
        return False
    for key, repair in list(record.get('specialist_repairs', {}).items()):
        candidate = repair.get('candidate', {})
        if (repair.get('status') != 'authored' or repair.get('before_sha256') != repair.get('after_sha256')
                or candidate.get('artifact') != 'experiments/specialists/DOMAIN_VALIDATION.md'):
            continue
        target = root / candidate['artifact']
        if hashlib.sha256(target.read_bytes()).hexdigest() != repair['after_sha256']:
            raise ValueError('Specialist document changed externally after blocked write')
        session = root / '.merak/agent-sessions' / (str(candidate.get('session_id', '')) + '.json')
        if not session.resolve().is_relative_to(root / '.merak/agent-sessions') or not session.is_file():
            return False
        messages = json.loads(session.read_bytes()).get('messages', [])
        if not any(m.get('role') == 'tool' and str(m.get('content', '')).startswith(
                'BLOCKED: workflow node results cannot write outside its owned artifacts.')
                and 'DOMAIN_VALIDATION.md' in str(m.get('content', '')) for m in messages):
            return False
        record.setdefault('specialist_repair_history', []).append(copy.deepcopy(repair))
        del record['specialist_repairs'][key]
        record['owner_scope_recovery_version'] = 1
        return True
    return False


async def repair_specialist_document(ctx, record: dict, entry: dict, paths: list[Path], issues: list[str], service) -> dict:
    """Return a trace-backed candidate; caller must independently review before committing it."""
    from ..agent.tools import invoke_skill
    from ..workflows.report_revision_store import save_report
    from ..workflows.review_audit import _source_bundle

    root = Path(ctx.run.project_path).resolve()
    artifact = (root / entry['artifact']).resolve()
    if not artifact.is_relative_to(root / 'experiments/specialists') or artifact.suffix != '.md':
        raise ValueError('Specialist repair requires its canonical Markdown artifact')
    inputs = [p for p in paths if p.resolve() != artifact]
    input_hash = _source_bundle(root, inputs)[0]
    repairs = record.setdefault('specialist_repairs', {})
    saved = repairs.get(entry['id'])
    if saved:
        if (saved.get('status') in {'authored', 'accepted'} and saved.get('input_hash') == input_hash
                and saved.get('after_sha256') == service._sha256(artifact)
                and service._invocation_trace_valid(root, saved['candidate'])[0]):
            return saved['candidate']
        raise ValueError('Specialist repair outcome is unresolved or inputs changed; do not replay it')
    prior_attempts = [r for r in record.get('specialist_content_history', []) if r['specialist_id'] == entry['id']]
    if len(prior_attempts) >= 2:
        raise ValueError('Specialist content repair budget exhausted')
    before = service._sha256(artifact)
    repairs[entry['id']] = {'status': 'editing', 'input_hash': input_hash, 'before_sha256': before,
        'issues': issues, 'previous_entry': copy.deepcopy(entry), 'started_at': time.time()}
    save_report(ctx.run_state, record)
    owner = next(n for n in ctx.host._get_default_nodes() if n.id == entry['node_id'])
    started, last_activity = time.time(), time.monotonic()
    async def event(value):
        nonlocal last_activity
        if ctx.host._agent_event_counts_as_progress(value):
            last_activity = time.monotonic()
        await ctx.host._emit(ctx.run, 'report_revision_progress', {'node_id': ctx.node.id,
            'report_id': record['id'], 'owner_node': entry['node_id'], 'skill': entry['skill'],
            'status': 'specialist_repair'})
    task = asyncio.create_task(invoke_skill(entry['skill'],
        'Repair only the existing specialist document to match the already accepted research contracts. '
        'Read the exact inputs below. Correct the listed inconsistency; preserve unrelated content. '
        'Do not change the hypothesis, method, metrics, data, code, source records or any acceptance state. '
        'Do not run experiments. If resolving a finding requires changing the accepted scientific design, '
        'leave the document unchanged and explain the conflict.\nTarget: ' + entry['artifact']
        + '\nInputs:\n' + '\n'.join(p.relative_to(root).as_posix() for p in inputs)
        + '\nIndependent findings:\n' + '\n'.join(issues), project_path=str(root),
        parent_context='report-specialist-repair', workflow_node_id=entry['node_id'], on_event=event,
        allowed_tools_override=['Read', 'Edit', 'Glob', 'Grep'], allowed_write_paths=[entry['artifact']],
        invocation_contract=f"Report {record['id']} specialist {entry['id']} repair {len(prior_attempts) + 1}",
        resume_input_fingerprint=input_hash, max_iterations=16))
    await ctx.host._await_agent_with_activity_watchdog(task=task, run=ctx.run, node=owner,
        is_revision=True, last_activity=lambda: last_activity)
    if _source_bundle(root, inputs)[0] != input_hash:
        raise ValueError('Specialist repair changed authoritative inputs')
    trace = service._latest_invocation_trace(root, entry['skill'], started)
    candidate = {**entry, 'status': 'completed', 'artifact_sha256': service._sha256(artifact),
        'session_id': trace.get('session_id', ''), 'invocation_trace': trace.get('trace_path', ''),
        'model_provider': trace.get('model_provider', ''), 'model_name': trace.get('model_name', ''),
        'completed_at': time.time()}
    if not service._artifact_valid(root, candidate)[0] or not service._invocation_trace_valid(root, candidate)[0]:
        raise ValueError('Specialist author did not produce a valid trace-backed document')
    repairs[entry['id']].update(status='authored', after_sha256=candidate['artifact_sha256'], candidate=candidate)
    save_report(ctx.run_state, record)
    return candidate


def next_specialist_attempt(ctx, record: dict, entry: dict, response: dict) -> None:
    """A rejected candidate may receive at most one further content repair, with evidence retained."""
    from ..workflows.report_revision_store import save_report
    history = record.setdefault('specialist_content_history', [])
    if sum(r['specialist_id'] == entry['id'] for r in history) >= 1:
        raise ValueError('Specialist remains invalid after two verified content attempts: ' + json.dumps(response))
    repair = record['specialist_repairs'][entry['id']]
    history.append({'specialist_id': entry['id'], 'repair': copy.deepcopy(repair), 'review': response})
    del record['specialist_repairs'][entry['id']]
    save_report(ctx.run_state, record)
