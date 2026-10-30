"""Transport recovery preserves repair budgets and never blindly replays an uncertain edit."""

from pathlib import Path


def transient_transport(error: BaseException) -> bool:
    from ..agent.remote_errors import RemoteCallError
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, RemoteCallError):
            return bool(error.retryable)
        if isinstance(error, (TimeoutError, ConnectionError)):
            return True
        error = error.__cause__ or error.__context__
    return False


def prepare_transport_resume(root: Path, record: dict) -> None:
    """An interrupted specialist may retry only with unchanged target and full input bundle."""
    import hashlib
    from ..services.specialist_inputs import input_relatives
    from .review_audit import _source_bundle
    from .report_revision_store import require_expected
    require_expected(root, record)
    for key, repair in list(record.get('specialist_repairs', {}).items()):
        if repair.get('status') != 'editing':
            continue
        prior = repair['previous_entry']
        target = root / prior['artifact']
        if hashlib.sha256(target.read_bytes()).hexdigest() != repair['before_sha256']:
            raise ValueError('Specialist write outcome is uncertain after transport interruption')
        inputs = [root / p for p in input_relatives(prior['node_id']) if (root / p).is_file()
                  and (root / p).resolve() != target.resolve()]
        if _source_bundle(root, inputs)[0] != repair['input_hash']:
            raise ValueError('Specialist inputs changed after transport interruption')
        record.setdefault('specialist_transport_history', []).append(repair)
        del record['specialist_repairs'][key]


def reopen_transport_reports(state) -> None:
    """Called only from explicit resume, including the previously misclassified HTTP failure."""
    def update(saved):
        if saved.get('status') == 'completed':
            return
        for record in saved.get('report_revisions', {}).values():
            legacy_http = str(record.get('error', '')).startswith('RemoteCallError: REMOTE_HTTP_ERROR:') and any(
                f'HTTP {code}' in record.get('error', '') for code in (429, 502, 503, 504))
            if record.get('status') == 'needs_attention' and legacy_http:
                if int(record.get('transport_interruptions', 0)) >= 3:
                    continue
                prepare_transport_resume(Path(state.project_path), record)
                record['status'] = 'refreshing' if record.get('refresh_completed') is not None else 'verifying'
                record['transport_interruptions'] = int(record.get('transport_interruptions', 0)) + 1
            elif record.get('status') == 'interrupted':
                prepare_transport_resume(Path(state.project_path), record)
                record['status'] = record.get('resume_stage', 'verifying')
    state.update_state(update)
