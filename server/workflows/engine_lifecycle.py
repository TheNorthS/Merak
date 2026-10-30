"""lifecycle workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class LifecycleMixin:
    def __init__(self):
        self._runs: dict[str, WorkflowRun] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._resume_claim_heartbeats: dict[str, asyncio.Task] = {}
        self._project_claim_heartbeats: dict[str, asyncio.Task] = {}
        self._project_start_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _project_key(project_path: str) -> str:
        return str(Path(project_path or '.').expanduser().resolve()).replace('\\', '/').casefold()

    @staticmethod
    def _start_node_attempt(node: WorkflowNode) -> float:
        """Open a fresh node lifecycle without leaking the prior terminal attempt."""
        started_at = time.time()
        node.status = NodeStatus.RUNNING
        node.session_id = None
        node.output = None
        node.error = None
        node.started_at = started_at
        node.finished_at = None
        return started_at

    @staticmethod
    def _mark_run_running(run: WorkflowRun) -> None:
        """Clear run-level completion data whenever execution is active again."""
        run.status = 'running'
        run.finished_at = None
        run.completion = {}

    def _active_run_for_project(self, project_path: str) -> Optional[str]:
        key = self._project_key(project_path)
        for run_id, task in list(self._running_tasks.items()):
            if task.done():
                self._running_tasks.pop(run_id, None)
                continue
            run = self._runs.get(run_id)
            if run and self._project_key(run.project_path) == key:
                return run_id
        return None

    def _ensure_agent_tools(self) -> None:
        """Workflow runs require real IDE tools; plain chat fallback is a hard error."""
        if not agent_engine._tool_definitions:
            from ..agent.tools import register_all_tools
            register_all_tools()
        if not agent_engine._tool_definitions:
            raise RuntimeError('Workflow tools are not registered; cannot execute research pipeline nodes.')

    @staticmethod
    def _phase_requires_revalidation(phase_record: dict[str, Any]) -> bool:
        return phase_requires_revalidation(phase_record)

    @staticmethod
    def _phase_is_durably_terminal(phase_record: Any) -> bool:
        return phase_is_durably_terminal(phase_record)

    @staticmethod
    def _training_check_blocks_current_mode(assessment: dict[str, Any], options: dict[str, Any]) -> bool:
        return training_check_blocks_current_mode(assessment, options)

    @classmethod
    def _resumable_phase_ids(cls, state: Optional[dict[str, Any]], selected_phase_ids: Optional[list[str]]=None) -> list[str]:
        return resumable_phase_ids(state, selected_phase_ids)

    @staticmethod
    def _phase_failed_from_timeout(phase_record: dict[str, Any]) -> bool:
        return phase_failed_from_timeout(phase_record)

    @staticmethod
    def _tool_artifact_path(data: dict[str, Any]) -> str:
        return tool_artifact_path(data)

    def _node_owns_artifact_path(self, node: WorkflowNode, run: WorkflowRun, raw_path: str) -> Optional[Path]:
        clean = str(raw_path or '').strip()
        if not clean:
            return None
        root = Path(run.project_path).expanduser().resolve()
        candidate = Path(clean).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        for owned in self._node_artifact_paths(node, run):
            target = owned.expanduser().resolve()
            if candidate == target:
                return candidate
            if target.is_dir():
                try:
                    candidate.relative_to(target)
                except ValueError:
                    continue
                return candidate
        return None

    @staticmethod
    def _load_run_events(project_path: str, run_id: str) -> list[dict[str, Any]]:
        path = Path(project_path).expanduser().resolve() / '.merak' / 'runs' / f'{run_id}.events.jsonl'
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        try:
            with path.open('r', encoding='utf-8-sig') as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict) and str(record.get('run_id') or '') == run_id:
                        records.append(record)
        except OSError:
            return []
        return records

    def _interrupted_primary_session_id(self, node: WorkflowNode, run: WorkflowRun) -> str:
        """Return a durable primary Agent session eligible for restart recovery."""
        state = RunState(run.project_path, run.id).load() or {}
        phase = dict((state.get('phases') or {}).get(node.id) or {})
        details = phase.get('details')
        details = details if isinstance(details, dict) else {}
        interruption = details.get('interruption') or {}
        if interruption.get('session_id'):
            return str(interruption['session_id'])
        revision = details.get('revision')
        revision = revision if isinstance(revision, dict) else {}
        phase_error = ' '.join((str(phase.get('error') or ''), str((revision.get('last_gate') or {}).get('summary') or '') if isinstance(revision.get('last_gate'), dict) else ''))
        transport_interrupted = bool(str(phase.get('status') or '') == 'running' or self._phase_failed_from_timeout(phase) or self._is_transport_revision_checkpoint(revision) or re.search('(?:502|503|429|timeout|timed out|stream stalled|incomplete chunked read|peer closed connection|connection reset)', phase_error, re.IGNORECASE))
        if not transport_interrupted:
            return ''
        candidate = ''
        for record in self._load_run_events(run.project_path, run.id):
            event = str(record.get('event') or '')
            data = record.get('data')
            data = data if isinstance(data, dict) else {}
            if str(data.get('node_id') or '') != node.id:
                continue
            session_id = str(data.get('session_id') or '')
            if event == 'skill_invocation_started' and (str(data.get('role') or 'primary') == 'primary' and session_id):
                candidate = session_id
                continue
            if not candidate or session_id != candidate:
                continue
            if event in {'skill_invocation_completed', 'skill_invocation_recovered'}:
                candidate = ''
                continue
            if event == 'skill_invocation_failed':
                failure = str(data.get('error') or '')
                if not re.search('(?:502|503|429|timeout|timed out|stream stalled|incomplete chunked read|peer closed connection|connection reset)', failure, re.IGNORECASE):
                    candidate = ''
        if not candidate:
            return ''
        transcript = Path(run.project_path).expanduser().resolve() / '.merak' / 'agent-sessions' / f'{candidate}.json'
        return candidate if transcript.is_file() else ''

    @staticmethod
    def _skill_invocation_for_session(project_path: str, run_id: str, node_id: str, session_id: str) -> Optional[dict[str, Any]]:
        path = Path(project_path).expanduser().resolve() / '.merak' / 'runs' / f'{run_id}.skills.json'
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        stage = dict((payload.get('stages') or {}).get(node_id) or {})
        primary = str(stage.get('primary') or '').lstrip('/')
        for invocation in reversed(list(stage.get('invocations') or [])):
            if not isinstance(invocation, dict):
                continue
            if str(invocation.get('session_id') or '') != session_id:
                continue
            if str(invocation.get('role') or '') != 'primary':
                continue
            skill_name = str(invocation.get('skill') or '').lstrip('/')
            if primary and skill_name != primary:
                continue
            if not (invocation.get('policy_loaded') is True and str(invocation.get('skill_sha256') or '').strip() and (int(invocation.get('skill_bytes') or 0) > 0)):
                continue
            return dict(invocation)
        return None

    def _persisted_timeout_artifact_evidence(self, node: WorkflowNode, run: WorkflowRun, phase_record: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Find a canonical write from this node's own primary session and run."""
        if not self._phase_failed_from_timeout(phase_record):
            return None
        active_primary_session = ''
        active_primary_skill = ''
        active_delegates: set[str] = set()
        pending_calls: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for record in self._load_run_events(run.project_path, run.id):
            event = str(record.get('event') or '')
            data = record.get('data')
            if not isinstance(data, dict) or str(data.get('node_id') or '') != node.id:
                continue
            timestamp = float(record.get('timestamp') or 0.0)
            if event == 'skill_invocation_started':
                role = str(data.get('role') or 'primary')
                session_id = str(data.get('session_id') or '')
                if role == 'primary':
                    active_primary_session = session_id
                    active_primary_skill = str(data.get('skill') or '').lstrip('/')
                    active_delegates.clear()
                elif session_id:
                    active_delegates.add(session_id)
                continue
            if event in {'skill_invocation_completed', 'skill_invocation_failed'}:
                session_id = str(data.get('session_id') or '')
                active_delegates.discard(session_id)
                continue
            if event == 'agent_tool_call':
                tool_name = str(data.get('tool') or '')
                if tool_name not in {'Write', 'Edit'}:
                    continue
                event_session = str(data.get('session_id') or '')
                pending_calls.append({'tool': tool_name, 'path': self._tool_artifact_path(data), 'session_id': event_session or active_primary_session, 'primary_session_id': active_primary_session, 'skill': active_primary_skill, 'delegate_active': bool(active_delegates), 'timestamp': timestamp, 'finished': False})
                continue
            if event != 'agent_tool_result':
                continue
            tool_name = str(data.get('tool') or '')
            if tool_name not in {'Write', 'Edit'}:
                continue
            call = next((item for item in reversed(pending_calls) if item['tool'] == tool_name and (not item['finished'])), None)
            if not call:
                continue
            call['finished'] = True
            event_session = str(data.get('session_id') or '')
            if event_session and event_session != call['primary_session_id']:
                continue
            if call['session_id'] != call['primary_session_id']:
                continue
            if call['delegate_active'] or not bool(data.get('success', True)):
                continue
            raw_path = self._tool_artifact_path(data) or str(call['path'] or '')
            artifact = self._node_owns_artifact_path(node, run, raw_path)
            if artifact is None or not self._artifact_has_content(artifact):
                continue
            invocation = self._skill_invocation_for_session(run.project_path, run.id, node.id, str(call['primary_session_id'] or ''))
            if invocation is None:
                continue
            candidates.append({'node_id': node.id, 'artifact': str(artifact), 'artifact_state': artifact_state(artifact), 'tool': tool_name, 'write_timestamp': timestamp, 'session_id': str(call['primary_session_id']), 'skill': str(invocation.get('skill') or call['skill']), 'execution_kind': str(invocation.get('execution_kind') or node.execution_kind or 'model_owned'), 'model_provider': str(invocation.get('model_provider') or ''), 'model_name': str(invocation.get('model_name') or '')})
        return max(candidates, key=lambda item: item['write_timestamp']) if candidates else None

    def _record_persisted_timeout_artifact_recovery(self, node: WorkflowNode, run: WorkflowRun, phase_record: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Turn a same-run successful write into a validation-only resume."""
        evidence = self._persisted_timeout_artifact_evidence(node, run, phase_record)
        if evidence is None:
            return None
        from ..services.skill_orchestrator import skill_orchestrator
        artifact = str(evidence['artifact'])
        summary = f'Recovered {node.id} after its primary model session wrote the canonical artifact before timing out: {artifact}. The artifact will now pass through canonicalization and independent quality gates; recovery is not acceptance.'
        skill_orchestrator.mark_execution(run.project_path, run.id, node.id, str(evidence['skill']), 'completed', role='primary', session_id=str(evidence['session_id']), output=summary, policy_loaded=True, execution_kind=str(evidence['execution_kind']), model_provider=str(evidence.get('model_provider') or ''), model_name=str(evidence.get('model_name') or ''), completion_mode='artifact_persisted_before_timeout')
        recovery = {**evidence, 'summary': summary, 'recovered_at': time.time(), 'validation_only': True}
        RunState(run.project_path, run.id).set_status(node.id, 'done', artifact=artifact, details={'summary': summary, 'timeout_artifact_recovery': recovery})
        return recovery

    async def execute(self, node_ids: list[str], project_path: str, research_direction: str='', effort: str='balanced', assurance: str='draft', pipeline_options: Optional[dict]=None, on_event: Optional[Callable]=None) -> str:
        """Start one workflow per project while allowing other projects to run."""
        key = self._project_key(project_path)
        lock = self._project_start_locks.setdefault(key, asyncio.Lock())
        async with lock:
            active_run_id = self._active_run_for_project(project_path)
            if active_run_id:
                raise ValueError(f'Project already has an active workflow: {active_run_id}. Resume or cancel that run instead of starting a duplicate.')
            claimed_options = dict(pipeline_options or {})
            requested_run_id = str(claimed_options.get('resume_run_id') or '').strip()
            internal_run_id = str(claimed_options.get('_project_claim_run_id') or '').strip()
            if requested_run_id and internal_run_id and (requested_run_id != internal_run_id):
                raise ValueError('Project workflow claim does not match resume_run_id')
            claim_run_id = requested_run_id or internal_run_id or uuid.uuid4().hex[:12]
            project_lease = ProjectRunLease(project_path)
            project_claim_token = str(claimed_options.get('_project_claim_token') or '')
            if project_claim_token:
                valid_claim = project_lease.renew(project_claim_token, run_id=claim_run_id, lease_seconds=self.PROJECT_CLAIM_TTL_SECONDS)
                if not valid_claim:
                    raise ValueError(f'Project workflow claim is stale or belongs to another run: {claim_run_id}')
            else:
                project_claim_token = project_lease.claim(run_id=claim_run_id, owner_id=f'workflow-engine:{uuid.uuid4().hex}', source='resume' if requested_run_id else 'fresh', lease_seconds=self.PROJECT_CLAIM_TTL_SECONDS)
                if not project_claim_token:
                    active_claim = project_lease.active_claim()
                    claimed_by = str(active_claim.get('run_id') or 'another process')
                    raise ValueError(f'Project already has an active workflow: {claimed_by}. Resume or cancel that run instead of starting a duplicate.')
            claimed_options['_project_claim_token'] = project_claim_token
            claimed_options['_project_claim_run_id'] = claim_run_id
            try:
                return await self._start_run(node_ids=node_ids, project_path=project_path, research_direction=research_direction, effort=effort, assurance=assurance, pipeline_options=claimed_options, on_event=on_event)
            except BaseException as exc:
                if claim_run_id not in self._running_tasks:
                    self._runs.pop(claim_run_id, None)
                    durable_run = RunState(project_path, claim_run_id)
                    if durable_run.load():
                        startup_error = self._exception_summary(exc)
                        durable_run.set_run_status('incomplete')
                        durable_run.update_state(lambda latest: {**latest, 'startup_error': startup_error, 'startup_failed_at': time.time()})
                project_lease.release(project_claim_token, run_id=claim_run_id)
                raise

    async def _heartbeat_resume_claim(self, run: WorkflowRun) -> None:
        """Renew a resume claim during long provider/model stages.
    
            A transient read/replace race must not cancel a healthy workflow. Retry
            several times and only cancel after consecutive failures, preserving a
            diagnostic event for recovery rather than misreporting operator cancel.
            """
        failures = 0
        try:
            while run.resume_claim_token:
                await asyncio.sleep(self.RESUME_CLAIM_HEARTBEAT_SECONDS)
                renewed = await asyncio.to_thread(RunState(run.project_path, run.id).renew_resume_claim, run.resume_claim_token, lease_seconds=self.RESUME_CLAIM_TTL_SECONDS)
                if renewed:
                    failures = 0
                    continue
                failures += 1
                logger.warning('resume_claim_renew_failed', run_id=run.id, consecutive_failures=failures)
                if failures < 3:
                    continue
                run.interruption_reason = 'Workflow resume ownership could not be renewed after three consecutive attempts. The run was stopped in a resumable state to prevent concurrent execution.'
                task = self._running_tasks.get(run.id)
                if task is not None and (not task.done()):
                    task.cancel()
                return
        except asyncio.CancelledError:
            return

    async def _heartbeat_project_claim(self, run: WorkflowRun) -> None:
        """Renew the project-wide lease with transient-failure tolerance."""
        failures = 0
        try:
            while run.project_claim_token:
                await asyncio.sleep(self.PROJECT_CLAIM_HEARTBEAT_SECONDS)
                renewed = await asyncio.to_thread(ProjectRunLease(run.project_path).renew, run.project_claim_token, run_id=run.id, lease_seconds=self.PROJECT_CLAIM_TTL_SECONDS)
                if renewed:
                    failures = 0
                    continue
                failures += 1
                logger.warning('project_claim_renew_failed', run_id=run.id, consecutive_failures=failures)
                if failures < 3:
                    continue
                run.interruption_reason = 'Project workflow ownership could not be renewed after three consecutive attempts. The run was stopped in a resumable state to prevent concurrent execution.'
                task = self._running_tasks.get(run.id)
                if task is not None and (not task.done()):
                    task.cancel()
                return
        except asyncio.CancelledError:
            return
