"""recovery workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class RecoveryMixin:
    async def resume_persisted_run(self, run_id: str, project_path: str, node_ids: Optional[list[str]]=None, research_direction: str='', effort: str='', assurance: str='', pipeline_options: Optional[dict]=None, on_event: Optional[Callable]=None, checkpoint_feedback: str='', resume_source: str='explicit') -> str:
        """Atomically claim a persisted run before any resume-side mutation."""
        durable_run = RunState(project_path, run_id)
        initial = durable_run.load()
        if not initial:
            raise ValueError(f'Run state not found: {run_id}')
        from .interruption_checkpoint import manual_resume_required
        if manual_resume_required(initial) and resume_source != 'explicit':
            raise ValueError('Interrupted execution requires explicit manual continuation.')
        if str(initial.get('status') or '') == 'cancelled' and resume_source != 'explicit':
            raise ValueError('An operator-stopped run requires explicit manual continuation; automatic recovery is disabled.')
        project_lease = ProjectRunLease(project_path)
        project_claim_token = project_lease.claim(run_id=run_id, owner_id=f'workflow-engine:{uuid.uuid4().hex}', source=f'resume:{resume_source}', lease_seconds=self.PROJECT_CLAIM_TTL_SECONDS)
        if not project_claim_token:
            active_claim = project_lease.active_claim()
            claimed_by = str(active_claim.get('run_id') or 'another process')
            raise ValueError(f'Project already has an active workflow: {claimed_by}. Resume or cancel that run instead of starting a duplicate.')
        try:
            claim_token = durable_run.claim_resume(owner_id=f'workflow-engine:{uuid.uuid4().hex}', expected_status=str(initial.get('status') or ''), source=resume_source, lease_seconds=self.RESUME_CLAIM_TTL_SECONDS)
        except BaseException:
            project_lease.release(project_claim_token, run_id=run_id)
            raise
        if not claim_token:
            project_lease.release(project_claim_token, run_id=run_id)
            raise ValueError(f'Run is already claimed by another active resume process: {run_id}')
        claimed_options = dict(pipeline_options or {})
        claimed_options['_resume_claim_token'] = claim_token
        claimed_options['_project_claim_token'] = project_claim_token
        claimed_options['_project_claim_run_id'] = run_id
        try:
            resumed_run_id = await self._resume_persisted_run_claimed(run_id=run_id, project_path=project_path, node_ids=node_ids, research_direction=research_direction, effort=effort, assurance=assurance, pipeline_options=claimed_options, on_event=on_event, checkpoint_feedback=checkpoint_feedback, resume_source=resume_source)
        except BaseException as exc:
            if run_id not in self._running_tasks:
                try:
                    resume_error = self._exception_summary(exc)
                    current = durable_run.load() or {}
                    if current.get('interruption'):
                        durable_run.update_state(lambda latest: latest['interruption'].update(manual_resume_required=True))
                    if str(current.get('status') or '') == 'running':
                        durable_run.set_run_status('incomplete')
                        durable_run.update_state(lambda latest: {**latest, 'resume_error': resume_error, 'resume_failed_at': time.time()})
                        try:
                            from ..services.workflow_event_journal import workflow_event_journal
                            workflow_event_journal.record(project_path, run_id, 'workflow_resume_failed', {'run_id': run_id, 'error': resume_error, 'resumable': True})
                        except Exception as journal_exc:
                            logger.warning('workflow resume failure journal error', run_id=run_id, error=str(journal_exc))
                except Exception as state_exc:
                    logger.warning('workflow resume failure state rollback error', run_id=run_id, error=str(state_exc))
            durable_run.release_resume_claim(claim_token)
            project_lease.release(project_claim_token, run_id=run_id)
            raise
        if resumed_run_id not in self._running_tasks:
            durable_run.release_resume_claim(claim_token)
            project_lease.release(project_claim_token, run_id=run_id)
        return resumed_run_id

    def get_persisted_run_state(self, project_path: str, run_id: str) -> Optional[dict]:
        """Read historical acceptance without validating or mutating the current worktree.

        Completed deliveries stay frozen. Sidebar edits have separate revision
        receipts; current artifact checks belong to an explicitly requested run.
        """
        return RunState(project_path, run_id).load()

    @staticmethod
    def _load_canonical_run_state_file(path: Path) -> Optional[dict]:
        """Load a workflow state file while rejecting run-scoped JSON sidecars."""
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('phases'), dict):
            return None
        run_id = str(data.get('run_id') or '').strip()
        if not run_id or path.name != f'{run_id}.json':
            return None
        return data

    def get_resumable_run_snapshot(self, project_path: str, run_id: str='') -> Optional[dict]:
        """Return a recovery snapshot even when an older run was mislabeled completed."""
        runs_dir = Path(project_path) / '.merak' / 'runs'
        if not runs_dir.exists():
            return None
        if run_id:
            candidates = [runs_dir / f'{run_id}.json']
        else:
            candidates = sorted(runs_dir.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            state = self._load_canonical_run_state_file(path)
            if state is None:
                continue
            resumable_ids = self._resumable_phase_ids(state)
            if not resumable_ids:
                continue
            phases = state.get('phases', {})
            return {'run_id': state.get('run_id') or path.stem, 'nodes_status': {phase_id: str(phase.get('status', 'pending')) for phase_id, phase in phases.items()}, 'current_node': resumable_ids[0], 'config': state.get('config', {}), 'saved_at': state.get('updated_at') or path.stat().st_mtime, 'resumable': True, 'recorded_status': state.get('status', 'unknown'), 'auto_rebuild_required': dict(state.get('auto_rebuild_required') or {}) if isinstance(state.get('auto_rebuild_required'), dict) else None}
        return None

    def list_persisted_runs(self, project_path: str) -> list[dict]:
        runs_dir = Path(project_path) / '.merak' / 'runs'
        if not runs_dir.exists():
            return []
        runs = []
        for path in sorted(runs_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            data = self._load_canonical_run_state_file(path)
            if data is None:
                continue
            refreshed = self.get_persisted_run_state(project_path, str(data.get('run_id') or path.stem))
            if refreshed is not None:
                data = refreshed
            phases = data.get('phases', {})
            resumable_ids = self._resumable_phase_ids(data)
            recorded_status = data.get('status', 'unknown')
            effective_status = 'incomplete' if recorded_status == 'completed' and resumable_ids else recorded_status
            completion = data.get('completion')
            completion = completion if isinstance(completion, dict) else {}
            runs.append({'run_id': data.get('run_id') or path.stem, 'status': effective_status, 'recorded_status': recorded_status, 'resumable': bool(resumable_ids), 'created_at': data.get('created_at'), 'updated_at': data.get('updated_at'), 'finished_at': data.get('finished_at'), 'completion': completion, 'execution_completed': bool(completion.get('execution_completed') if completion else data.get('execution_completed')), 'submission_ready': bool(completion.get('submission_ready') if completion else data.get('submission_ready')), 'completion_class': str(completion.get('completion_class') or data.get('completion_class') or ''), 'config': dict(data.get('config') or {}) if isinstance(data.get('config'), dict) else {}, 'auto_rebuild_required': dict(data.get('auto_rebuild_required') or {}) if isinstance(data.get('auto_rebuild_required'), dict) else None, 'phases': [{'id': phase_id, 'name': phase.get('name', phase_id), 'status': phase.get('status', 'pending'), 'artifact': phase.get('artifact', ''), 'verdict_id': phase.get('verdict_id', ''), 'reviewer': phase.get('reviewer', '')} for phase_id, phase in phases.items()]})
        return runs

    async def _wait_for_human_checkpoint(self, run: WorkflowRun, node: WorkflowNode, timeout_seconds: int, context: Optional[dict]=None) -> str:
        """Pause before a node so the user can inject guidance, extend the wait, or auto-continue."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        timeout_seconds = max(1, int(timeout_seconds))
        run.checkpoint_future = future
        run.checkpoint_node_id = node.id
        run.checkpoint_deadline = time.time() + timeout_seconds
        run.checkpoint_resolution = ''
        run.status = 'paused'
        checkpoint_context = dict(context or {})
        is_revision = checkpoint_context.get('checkpoint_kind') == 'research_revision'
        await self._emit(run, 'checkpoint_waiting', {**checkpoint_context, 'node_id': node.id, 'checkpoint_id': f'{run.id}:{node.id}:human', 'name': node.name, 'timeout_seconds': timeout_seconds, 'deadline_at': run.checkpoint_deadline, 'message': 'The node still has research-quality issues. You may redirect the next revision cycle; it will continue automatically on timeout.' if is_revision else 'You may provide adjustment feedback for the next node. The workflow will continue automatically on timeout.'})
        payload: dict | str = {'feedback': '', 'auto': True}
        try:
            while True:
                remaining = max(0.0, run.checkpoint_deadline - time.time())
                if remaining <= 0:
                    break
                try:
                    payload = await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
                    break
                except asyncio.TimeoutError:
                    if run.checkpoint_deadline > time.time():
                        continue
                    break
            if not future.done() and run.status == 'paused':
                await self._emit(run, 'checkpoint_auto_resumed', {'run_id': run.id, 'node_id': node.id, 'timeout_seconds': timeout_seconds})
        finally:
            run.checkpoint_future = None
            run.checkpoint_deadline = 0.0
            if run.status == 'paused':
                self._mark_run_running(run)
        if run.status == 'cancelled':
            run.checkpoint_resolution = 'cancelled'
            return ''
        feedback = ''
        if isinstance(payload, dict):
            feedback = str(payload.get('feedback') or '').strip()
            if payload.get('auto'):
                run.checkpoint_resolution = 'timeout'
            elif feedback:
                run.checkpoint_resolution = 'feedback'
            else:
                run.checkpoint_resolution = 'continued'
        elif payload:
            feedback = str(payload).strip()
            run.checkpoint_resolution = 'feedback' if feedback else 'continued'
        else:
            run.checkpoint_resolution = 'timeout'
        if feedback:
            from .operator_feedback import record_operator_feedback
            record_operator_feedback(RunState(run.project_path, run.id), node.id, feedback)
        return feedback

    async def extend_checkpoint(self, run_id: str, seconds: int=300) -> dict:
        """Extend an active human checkpoint without restarting or duplicating the workflow."""
        run = self._runs.get(run_id)
        if not run or run.status != 'paused' or (not run.checkpoint_future):
            raise ValueError('Workflow is no longer waiting at a human checkpoint')
        added = max(30, min(1800, int(seconds or 300)))
        now = time.time()
        base = max(now, run.checkpoint_deadline)
        run.checkpoint_deadline = min(base + added, now + 7200)
        remaining = max(1, int(round(run.checkpoint_deadline - now)))
        await self._emit(run, 'checkpoint_extended', {'run_id': run.id, 'node_id': run.checkpoint_node_id, 'added_seconds': added, 'remaining_seconds': remaining, 'deadline_at': run.checkpoint_deadline})
        return {'run_id': run.id, 'node_id': run.checkpoint_node_id, 'added_seconds': added, 'remaining_seconds': remaining, 'deadline_at': run.checkpoint_deadline}

    async def resume_run(self, run_id: str, feedback: str='') -> bool:
        """Resume a paused workflow checkpoint, optionally with user guidance."""
        run = self._runs.get(run_id)
        if not run or run.status != 'paused':
            return False
        clean_feedback = (feedback or '').strip()
        if run.checkpoint_node_id:
            RunState(run.project_path, run.id).consume_human_checkpoint(run.checkpoint_node_id, resolution='feedback' if clean_feedback else 'continued', feedback_supplied=bool(clean_feedback))
        payload = {'feedback': clean_feedback, 'auto': False}
        if run.checkpoint_future and (not run.checkpoint_future.done()):
            run.checkpoint_future.set_result(payload)
        self._mark_run_running(run)
        await self._emit(run, 'checkpoint_resumed', {'run_id': run_id, 'node_id': run.checkpoint_node_id, 'has_feedback': bool(clean_feedback)})
        return True

    def _topological_sort(self, nodes: list[WorkflowNode]) -> list[WorkflowNode]:
        """拓扑排序（按依赖关系）"""
        node_map = {n.id: n for n in nodes}
        visited = set()
        result = []
    
        def dfs(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            node = node_map.get(node_id)
            if not node:
                return
            for dep in node.depends_on:
                if dep in node_map:
                    dfs(dep)
            result.append(node)
        for n in nodes:
            dfs(n.id)
        return result

    def _get_default_nodes(self) -> list[WorkflowNode]:
        """预定义的工作流节点 — 使用真实 MERAK skill 名称"""
        from ..contracts.workflow_nodes import WORKFLOW_NODES
        return [WorkflowNode(**{**item, "skill": "/" + item["skill"]}) for item in WORKFLOW_NODES]

    async def _emit(self, run: WorkflowRun, event_type: str, data: dict):
        """发送事件（callback + WebSocket 广播）"""
        logger.info('Workflow event emitted', evt=event_type, node=data.get('node_id', ''))
        try:
            from ..services.workflow_event_journal import workflow_event_journal
            await workflow_event_journal.record_async(run.project_path, run.id, event_type, data)
        except Exception as e:
            logger.warning('Workflow event journal error', error=str(e))
        if run.on_event:
            try:
                if asyncio.iscoroutinefunction(run.on_event):
                    await run.on_event(event_type, data)
                else:
                    run.on_event(event_type, data)
            except Exception as e:
                logger.warning('on_event callback error', error=str(e))
        try:
            from ..ws.router import broadcast_workflow_event
            await broadcast_workflow_event(event_type, {'run_id': run.id, **data})
        except Exception as e:
            logger.warning('WebSocket broadcast error', error=str(e))

    def get_run(self, run_id: str) -> Optional[dict]:
        """获取运行状态"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {'id': run.id, 'status': run.status, 'created_at': run.created_at, 'finished_at': run.finished_at, 'project_path': run.project_path, 'completion': run.completion, 'selected_node_ids': list(run.options.get('selected_node_ids') or [node.id for node in run.nodes]), 'checkpoint': {'node_id': run.checkpoint_node_id, 'deadline_at': run.checkpoint_deadline, 'remaining_seconds': max(0, int(run.checkpoint_deadline - time.time())) if run.checkpoint_deadline else 0} if run.status == 'paused' else None, 'nodes': [{'id': n.id, 'name': n.name, 'skill': n.skill, 'execution_kind': n.execution_kind, 'runtime_service': n.runtime_service, 'policy_required': n.policy_required, 'status': n.status.value, 'started_at': n.started_at, 'finished_at': n.finished_at, 'error': n.error} for n in run.nodes]}

    def list_runs(self) -> list[dict]:
        """列出所有运行"""
        runs: list[dict] = []
        for run in sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True):
            snapshot = self.get_run(run.id)
            if snapshot is None:
                continue
            snapshot['node_count'] = len(run.nodes)
            runs.append(snapshot)
        return runs

    async def cancel_run(self, run_id: str):
        """Return only after cancellation has joined the run and saved its stop."""
        run = self._runs.get(run_id)
        if run:
            from .interruption_checkpoint import record_interruption
            current = next((node for node in run.nodes if node.status in {NodeStatus.RUNNING, NodeStatus.QUEUED}), None)
            record_interruption(run, current, 'cancelled by operator', kind='cancelled')
            run.status = 'cancelled'
            run.interruption_reason = ''
            if run.checkpoint_future and (not run.checkpoint_future.done()):
                run.checkpoint_future.set_result({'feedback': '', 'cancelled': True})
            for node in run.nodes:
                if node.status == NodeStatus.RUNNING and node.session_id:
                    try:
                        await agent_engine.cancel(node.session_id)
                    except Exception as exc:
                        logger.warning('Active workflow agent cancellation failed', run_id=run_id, node_id=node.id, session_id=node.session_id, error=str(exc))
            task = self._running_tasks.get(run_id)
            if task is not None and task is not asyncio.current_task():
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                claim = ProjectRunLease(run.project_path).active_claim()
                if claim.get('token') == run.project_claim_token:
                    from .run_start_lifecycle import _cleanup_lifecycle
                    await _cleanup_lifecycle(self, run, task)
                    if ProjectRunLease(run.project_path).active_claim().get('token') == run.project_claim_token:
                        raise RuntimeError('Workflow stopped but ownership cleanup is incomplete; retry cleanup before resuming')
            # A stop during startup may have no initialized execution context.
            # The operator stop must still be durable and never auto-recover.
            run.finished_at = time.time()
            for node in run.nodes:
                if node.status in {NodeStatus.RUNNING, NodeStatus.QUEUED}:
                    state = RunState(run.project_path, run.id)
                    phase = (state.load() or {}).get('phases', {}).get(node.id, {})
                    if phase.get('status') not in TERMINAL_PHASE_STATES:
                        state.set_status(node.id, 'pending', error='cancelled by operator')
                    node.status = NodeStatus.IDLE
                    node.finished_at = run.finished_at
                    node.error = 'cancelled by operator'
            # Phase mutation clears terminal run fields; commit the operator
            # stop after all phase cleanup so it cannot be reset to running.
            RunState(run.project_path, run.id).set_run_status('cancelled')

    async def shutdown(self) -> None:
        """Stop active workflows as resumable platform interruptions.
    
            Uvicorn/Electron restarts used to tear down the event loop while workflow
            tasks and their lease heartbeats were still alive. That could leave a
            durable ``running`` record with no worker, or mislabel the interruption
            as a researcher cancellation. Give each run the normal cancellation
            path, then join children and release both ownership leases explicitly.
            """
        active: list[tuple[str, WorkflowRun, asyncio.Task]] = []
        for run_id, task in list(self._running_tasks.items()):
            run = self._runs.get(run_id)
            if run is None or task.done():
                continue
            run.interruption_reason = 'The MERAK backend stopped or restarted while this workflow was running. The run remains resumable from its last durable phase.'
            active.append((run_id, run, task))
            task.cancel()
        if active:
            await asyncio.gather(*(task for _, _, task in active), return_exceptions=True)
        heartbeat_tasks = [*self._resume_claim_heartbeats.values(), *self._project_claim_heartbeats.values()]
        for task in heartbeat_tasks:
            if not task.done():
                task.cancel()
        if heartbeat_tasks:
            await asyncio.gather(*heartbeat_tasks, return_exceptions=True)
        for run_id, run, _ in active:
            try:
                if run.resume_claim_token:
                    await asyncio.to_thread(RunState(run.project_path, run_id).release_resume_claim, run.resume_claim_token)
                if run.project_claim_token:
                    await asyncio.to_thread(ProjectRunLease(run.project_path).release, run.project_claim_token, run_id=run_id)
            except Exception as exc:
                logger.warning('Workflow ownership cleanup failed during shutdown', run_id=run_id, error=str(exc))
        self._running_tasks.clear()
        self._resume_claim_heartbeats.clear()
        self._project_claim_heartbeats.clear()
