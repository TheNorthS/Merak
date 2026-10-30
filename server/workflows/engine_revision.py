"""revision workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class RevisionMixin:
    @staticmethod
    def _compile_failure_summary(compile_result: Any) -> str:
        """Keep source locations and useful context in revision diagnostics."""
        messages: list[str] = []
        for item in compile_result.errors[:6]:
            location = ''
            if item.file:
                location = str(item.file)
                if item.line:
                    location += f':{item.line}'
                location += ': '
            source_excerpt = ''
            if item.file and item.line:
                try:
                    source_lines = Path(item.file).read_text(encoding='utf-8', errors='replace').splitlines()
                    if 0 < item.line <= len(source_lines):
                        source_excerpt = f' [source: {source_lines[item.line - 1].strip()[:240]}]'
                except OSError:
                    pass
            messages.append(f'{location}{item.message}{source_excerpt}')
        return '; '.join(messages) or compile_result.log_output[-1200:]

    @staticmethod
    def _refresh_compiled_artifact_record(source_root: Path, record_name: str, pdf_name: str, *, pages: int | None=None, compile_time_ms: int | None=None, warning_count: int | None=None) -> None:
        """Refresh the current compiler-owned record after a successful build."""
        from ..services.paper_compiler import paper_compiler
        paper_compiler.refresh_build_record(source_root, record_name, pdf_name, pages=pages, compile_time_ms=compile_time_ms, warning_count=warning_count)

    @classmethod
    def _revision_diagnostics_for_owner(cls, diagnostics: dict[str, Any], owner_id: str, default_owner_id: str='') -> dict[str, Any]:
        """Limit a multi-owner gate to the artifacts owned by this repair."""
        findings = [dict(item) for item in diagnostics.get('findings', []) if isinstance(item, dict)]
        explicitly_owned = [item for item in findings if str(item.get('upstream_node') or item.get('owner_node') or '').strip()]
        if not explicitly_owned:
            return diagnostics
        scoped_findings = [item for item in findings if str(item.get('upstream_node') or item.get('owner_node') or '').strip() == owner_id or (not str(item.get('upstream_node') or item.get('owner_node') or '').strip() and (not default_owner_id or default_owner_id == owner_id))]
        if not scoped_findings or len(scoped_findings) == len(findings):
            return diagnostics
        target_files = cls._revision_target_files([item.get('target_files') for item in scoped_findings])
        asset_ids = cls._revision_asset_ids([item.get('asset_ids') for item in scoped_findings])
        issues = list(dict.fromkeys((str(item.get('message') or item.get('plain_message') or '').strip() for item in scoped_findings if str(item.get('message') or item.get('plain_message') or '').strip())))
        finding_ids = list(dict.fromkeys((str(item.get('id') or '').strip() for item in scoped_findings if str(item.get('id') or '').strip())))
        remediations = list(dict.fromkeys((str(item.get('remediation') or '').strip() for item in scoped_findings if str(item.get('remediation') or '').strip())))
        return {**diagnostics, 'issues': issues, 'risk_remediations': remediations, 'findings': scoped_findings, 'active_owner_id': owner_id, 'repair_scope': {'finding_ids': finding_ids, 'target_files': target_files, 'asset_ids': asset_ids}}

    @staticmethod
    def _revision_intervention_kind(node: WorkflowNode, diagnostics: dict[str, Any]) -> str:
        """Separate researcher choices from platform/artifact repair failures."""
        text = ' '.join([str(diagnostics.get('reason') or ''), str(diagnostics.get('summary') or ''), *[str(item) for item in diagnostics.get('issues', [])]]).casefold()
        researcher_decision_markers = ('researcher decision required', 'requires researcher decision', 'change the hypothesis', 'change hypothesis', 'hypothesis scope choice', 'novelty scope choice', 'evidence policy decision', 'ethical approval', 'ethics approval', 'informed consent', 'data access approval', 'dataset license decision', 'cost commitment', 'budget approval', '需要研究者决定', '需要研究者选择', '修改研究假设', '更改研究假设', '新颖性范围选择', '证据政策决策', '伦理审批', '知情同意', '数据访问授权', '数据集许可决策', '成本承诺', '预算批准')
        if any((marker in text for marker in researcher_decision_markers)):
            return 'researcher_decision'
        if node.id == 'novelty' and any((marker in text for marker in ('change the selected idea', 'select a different idea', 'novelty collision requires'))):
            return 'researcher_decision'
        return 'platform_repair'

    @staticmethod
    def _new_workflow_risk_findings(run: WorkflowRun, snapshot: dict[str, Any], current_node_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return newly observed risks once, while retaining active blockers."""
        newly_observed: list[dict[str, Any]] = []
        active_blockers: list[dict[str, Any]] = []
        for audited_id, report in snapshot.get('nodes', {}).items():
            if not isinstance(report, dict):
                continue
            for finding in report.get('findings', []):
                if not isinstance(finding, dict):
                    continue
                severity = str(finding.get('severity') or 'warning')
                payload = {'node_id': str(audited_id), 'finding_id': str(finding.get('id') or ''), 'severity': severity, 'owner_node': str(finding.get('owner_node') or finding.get('upstream_node') or audited_id), 'plain_message': str(finding.get('plain_message') or finding.get('message') or ''), 'remediation': str(finding.get('remediation') or '')}
                marker = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
                if marker not in run.risk_fingerprints:
                    run.risk_fingerprints.add(marker)
                    newly_observed.append(payload)
                if severity == 'blocker' and audited_id != current_node_id:
                    active_blockers.append(payload)
        return {'new_findings': newly_observed, 'latent_blockers': active_blockers}

    def _dependent_phase_ids(self, owner_id: str, available_phase_ids: set[str]) -> list[str]:
        """Return canonical descendants of an upstream scientific owner."""
        definitions = self._get_default_nodes()
        descendants: set[str] = set()
        changed = True
        while changed:
            changed = False
            for definition in definitions:
                if definition.id not in available_phase_ids or definition.id in descendants:
                    continue
                if owner_id in definition.depends_on or any((dependency in descendants for dependency in definition.depends_on)):
                    descendants.add(definition.id)
                    changed = True
        return [definition.id for definition in definitions if definition.id in descendants]

    def _refresh_run_nodes_from_state(self, run: WorkflowRun, run_state: RunState) -> None:
        """Expand a resumed subset and align in-memory statuses with RunState."""
        state = run_state.load() or {}
        phases = state.get('phases', {})
        existing = {node.id: node for node in run.nodes}
        ordered: list[WorkflowNode] = []
        for definition in self._get_default_nodes():
            if definition.id not in phases:
                continue
            node = existing.get(definition.id, definition)
            phase_status = str(phases.get(definition.id, {}).get('status') or 'pending')
            node.status = NodeStatus.COMPLETED if phase_status in TERMINAL_PHASE_STATES else NodeStatus.IDLE
            node.error = None
            node.started_at = None
            node.finished_at = None
            ordered.append(node)
        ordered.extend((node for node in run.nodes if node.id not in {item.id for item in ordered}))
        run.nodes = ordered

    async def _prepare_research_loop_restart(self, *, run: WorkflowRun, run_state: RunState, owner_id: str, reason: str, opts: dict[str, Any], consumer_id: str='') -> str:
        """Reopen all descendants after a real upstream scientific change."""
        try:
            configured_limit = int(opts.get('max_research_loop_cycles') or 3)
        except (TypeError, ValueError):
            configured_limit = 3
        max_cycles = min(6, max(1, configured_limit))
        state = run_state.load() or {}
        phase_ids = set((state.get('phases') or {}).keys())
        from .owner_revision_scope import owner_revision_dependents
        descendants = owner_revision_dependents(self, owner_id, consumer_id, phase_ids)
        if not descendants:
            return ''
        owner_signature = self._revision_artifact_signature(run.project_path, owner_id, opts)
        transaction = run_state.begin_reconciliation_transaction(owner_id=owner_id, artifact_signature=owner_signature, reason=reason, invalidated_phase_ids=descendants, maximum_transactions=max_cycles)
        if transaction.get('duplicate'):
            await self._emit(run, 'research_loop_coalesced', {'owner_node_id': owner_id, 'artifact_signature': owner_signature, 'cycle': int(transaction.get('count') or 0), 'max_cycles': max_cycles, 'reason': reason, 'message': 'The same upstream artifact generation was already reconciled; downstream phases were not invalidated again.'})
            return ''
        if transaction.get('exhausted'):
            await self._emit(run, 'research_loop_exhausted', {'owner_node_id': owner_id, 'cycle': int(transaction.get('count') or 0), 'max_cycles': max_cycles, 'reason': reason})
            from .reconciliation_budget import ReconciliationBudgetExhausted
            raise ReconciliationBudgetExhausted(f'Upstream {owner_id} repair is saved; downstream rebuild limit {max_cycles} reached. Resume the pending upstream stages before requesting another consumer review.')
        if not transaction.get('started'):
            raise RuntimeError('Cannot persist the upstream rebuild transaction')
        next_cycle = int(transaction.get('count') or 1)
        for phase_id in descendants:
            run_state.reopen_for_upstream_change(phase_id, owner_id=owner_id, reason=reason, loop_cycle=next_cycle)
        opts['_research_loop_cycle'] = next_cycle
        run.options['_research_loop_cycle'] = next_cycle
        self._refresh_run_nodes_from_state(run, run_state)
        await self._emit(run, 'research_loop_restarted', {'owner_node_id': owner_id, 'restart_from_node_id': descendants[0], 'invalidated_node_ids': descendants, 'artifact_signature': owner_signature, 'transaction_id': str(dict(transaction.get('transaction') or {}).get('id') or ''), 'cycle': next_cycle, 'max_cycles': max_cycles, 'reason': reason})
        return descendants[0]

    @classmethod
    def _build_revision_decision_brief(cls, node: WorkflowNode, diagnostics: dict, round_number: int, max_revision_rounds: int) -> dict:
        """Build a concise decision brief; raw gate output remains secondary."""
        raw_issues = [str(item).strip() for item in diagnostics.get('issues', []) if str(item).strip()]
        plain_issues = [cls._humanize_revision_issue(item) for item in raw_issues[:8]]
        issue_count = max(1, len(raw_issues))
        impacts = {'idea': '如果研究问题、机制或证伪条件没有确认，后续实验可能验证的是另一个问题，造成整体 Idea 漂移。', 'novelty': '如果新颖性证据尚未闭合，继续实现可能重复已有工作，论文的核心贡献将难以成立。', 'exp-design': '如果实现、配置和方法契约没有对齐，后续基线、消融和统计结果将无法可靠归因到选定 Idea。', 'exp-run': '如果执行证据或运行状态不完整，实验结果可能不可复现，也不能安全用于论文结论。', 'results': '如果结果与运行证据没有对应，当前数字不能支持科研 claim，也不应进入图表或论文。', 'figure': '如果图表没有绑定真实结果或方法结构，读者可能被误导，论文也无法追溯图中证据来源。', 'narrative': '如果叙事超出已有证据，论文主张会比实验支持范围更强，增加审稿风险。', 'paper': '如果论文 claim、引用或结果与证据不一致，继续编译只会得到形式完整但科研上不可提交的稿件。', 'review': '如果关键审稿问题尚未解决，停止迭代会把已知逻辑漏洞带入最终稿。', 'audit': '如果审计项仍然失败，当前研究包不具备完整的可追溯性和复现条件。', 'compile': '如果编译产物与源文件不一致或缺失，最终 PDF 不能作为可靠交付物。', 'ppt': '如果演示内容没有绑定论文证据，汇报材料可能放大未经支持的结论。'}
        actions = ['查看下面的核心问题，修改对应的标准产物后选择“产物已修改，重新验收”。', '如果系统误解了你的实现或研究边界，在反馈框指出正确文件、符号或约束，让智能体进行一次定向修订。', '暂时无法判断时选择“稍后处理”；节点和问题会保留，但后续阶段不会被放行。']
        risk_actions = [str(item).strip() for item in diagnostics.get('risk_remediations', []) if str(item).strip()]
        if risk_actions:
            actions = list(dict.fromkeys([*risk_actions[:3], *actions]))
        if any(('missing declared symbol' in item.casefold() for item in raw_issues)):
            actions.insert(0, '优先核对 METHOD_CONTRACT.json 声明的 symbol 是否与代码中的模块级函数、类或变量名称完全一致。')
        if any(('missing config key' in item.casefold() for item in raw_issues)):
            actions.insert(0, '优先核对方法契约中的配置路径与 main.yaml 的真实层级，避免只在说明文字中出现该字段。')
        reason = str(diagnostics.get('reason') or '').casefold()
        if 'no semantic progress' in reason:
            progress = diagnostics.get('revision_progress')
            progress = progress if isinstance(progress, dict) else {}
            classification = str(
                diagnostics.get('stall_classification')
                or progress.get('stall_classification') or ''
            )
            if classification == 'ineffective_content_change':
                what_happened = f'产物内容已经变化，但没有解决任何结构化问题。可能原因是修改无效、修改被其他生产者覆盖，或生成器与门禁契约冲突。系统已在 {round_number}/{max_revision_rounds} 轮内停止重复调用。'
            else:
                what_happened = f'产物没有发生可检测的内容变化，结构化问题也保持不变。系统已在 {round_number}/{max_revision_rounds} 轮内停止重复调用。'
        elif 'deterministic figure repair' in reason:
            what_happened = '结构化图片生成器已经尝试补齐源文件、预览和元数据，但渲染产物仍未满足验收。系统没有把渲染器故障继续交给语言模型反复改图。'
        elif 'revision execution interrupted' in reason:
            what_happened = '模型连接连续中断，科研产物没有完成新的有效修订。连接错误未计入科研修订轮数，系统已保留断点。'
        elif 'revision execution failed' in reason:
            what_happened = '节点修订执行本身发生异常，系统保留了异常类型和责任节点，并没有把它伪装成模型连接超时。'
        else:
            what_happened = f'系统已完成 {round_number} 轮自动修订并重新检查标准产物；最新结果仍未达到门槛，因此在 {max_revision_rounds} 轮上限内暂停。'
        headline = f'{node.name}仍有 {issue_count} 项关键问题未通过验收'
        return {'headline': headline, 'what_happened': what_happened, 'research_impact': impacts.get(node.id, '如果在产物与验收要求不一致时继续，下游结论将缺少可靠、可追溯的科研证据。'), 'plain_issues': plain_issues or ['当前节点未通过独立验收，但校验器没有提供更具体的结构化问题。请查看技术详情或报告。'], 'system_actions': [f'已执行并重新验收当前节点；自动修订计数为 {round_number}/{max_revision_rounds}。', '已停止继续调用模型，避免在同一问题上无限循环。', '已保留当前产物、质量报告和恢复断点。'], 'recommended_actions': actions[:4], 'decision_question': '请选择：先修改产物后重新验收，或提交明确反馈进行一次定向修订。', 'protected_state': '当前节点仍未通过；系统没有跳过质量门，也没有放行依赖它的后续节点。', 'technical_details': raw_issues}

    @staticmethod
    def _is_recoverable_research_error(exc: Exception) -> bool:
        """Quality/artifact problems are revisable; permission/security faults are not."""
        from ..agent.tool_deadline import ToolCancellationUnconfirmed
        if isinstance(exc, (PermissionError, ToolCancellationUnconfirmed)):
            return False
        text = str(exc).lower()
        if any((marker in text for marker in ('permission denied', 'outside project', 'path traversal', 'security policy', 'credential', 'no module named', 'cannot import name'))):
            return False
        return isinstance(exc, (RuntimeError, TimeoutError, ConnectionError, OSError, ValueError))

    @staticmethod
    def _is_transport_research_error(exc: Exception) -> bool:
        """Return whether a revision failure belongs to the transport budget.
    
            Revision code also raises RuntimeError for malformed artifacts,
            renderer failures, and schema problems. Treating every RuntimeError as
            a provider outage hides the real owner and can persist blank
            revision-execution-interrupted records.
            """
        from ..agent.tool_response_protocol import ToolResponseProtocolError
        from ..agent.remote_errors import RemoteCallError
        cause, seen = exc, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, RemoteCallError):
                return cause.retryable
            cause = cause.__cause__
        from ..agent.tool_deadline import ToolCancellationUnconfirmed

        if isinstance(exc, ToolCancellationUnconfirmed):
            return False
        if isinstance(exc, (TimeoutError, ConnectionError, ToolResponseProtocolError)):
            return True
        text = str(exc).strip().casefold()
        if not text:
            return False
        return any((marker in text for marker in ('model transport exhausted', 'model_tool_arguments_invalid', 'model_tool_response_incomplete', 'model_tool_response_truncated', 'api error 502', '502 bad gateway', 'bad gateway', 'api error 503', 'api request timeout', 'model request timeout', 'request timed out', 'provider timed out', 'stream stalled', 'incomplete chunked read', 'peer closed connection', 'connection reset', 'connection refused', 'connection aborted', '503 service unavailable', '504 gateway timeout', 'gateway timeout', '529 overloaded', '429 too many requests', 'rate limit', 'temporarily unavailable', 'server disconnected', 'remote protocol error', 'network error')))

    async def _sleep_with_transport_heartbeat(self, *, run: WorkflowRun, node_id: str, operation_name: str, stage_id: str, delay_seconds: float, attempt: int, max_attempts: int) -> None:
        """Back off without making an unattended workflow look stalled."""
        remaining = max(0.0, float(delay_seconds))
        heartbeat_interval = 30.0
        while remaining > 0:
            sleep_for = min(heartbeat_interval, remaining)
            await asyncio.sleep(sleep_for)
            remaining = max(0.0, remaining - sleep_for)
            if remaining > 0:
                await self._emit(run, 'node_transport_heartbeat', {'node_id': node_id, 'operation': operation_name, 'stage_id': stage_id, 'attempt': attempt, 'max_attempts': max_attempts, 'remaining_delay_seconds': round(remaining, 1), 'message': '模型服务暂时不可用，工作流仍在自动重试。'})

    async def _execute_with_model_transport_retry(self, *, run: WorkflowRun, node_id: str, operation_name: str, operation: Callable[[], Any], opts: Optional[dict[str, Any]]=None, stage_id: str='', recovery_probe: Optional[Callable[[], Any]]=None) -> Any:
        """Invoke an operation once; request retries belong to the agent transport.

        Whole-stage retries hide failure points and multiply model costs. A failed
        operation leaves durable state for explicit manual continuation.
        """
        started = time.monotonic()
        if run.status == 'cancelled':
            raise asyncio.CancelledError()
        try:
            result = operation()
            return await result if inspect.isawaitable(result) else result
        except Exception as error:
            if self._is_transport_research_error(error):
                record = {'operation': operation_name, 'stage_id': stage_id, 'attempt': 1,
                          'max_attempts': 1, 'elapsed_seconds': round(time.monotonic() - started, 1),
                          'error': self._exception_summary(error), 'error_category': 'transport',
                          'exhausted': True, 'retryable': True, 'manual_resume_required': True}
                RunState(run.project_path, run.id).record_transport_retry(node_id, record)
                await self._emit(run, 'node_transport_exhausted', {'node_id': node_id, **record})
            raise

    @staticmethod
    def _transport_checkpoint_schedule(saved_revision: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
        """Return a durable, bounded backoff schedule after provider exhaustion."""
        try:
            previous_count = max(0, int(saved_revision.get('transport_retry_count') or 0))
        except (TypeError, ValueError):
            previous_count = 0
        try:
            base_delay = min(3600.0, max(5.0, float(opts.get('model_transport_checkpoint_base_delay_seconds') or 60.0)))
        except (TypeError, ValueError):
            base_delay = 60.0
        try:
            max_delay = min(6 * 3600.0, max(base_delay, float(opts.get('model_transport_checkpoint_max_delay_seconds') or 1800.0)))
        except (TypeError, ValueError):
            max_delay = max(base_delay, 1800.0)
        try:
            max_retries = min(12, max(1, int(opts.get('model_transport_checkpoint_max_retries') or 4)))
        except (TypeError, ValueError):
            max_retries = 4
        retry_count = previous_count + 1
        delay = min(max_delay, base_delay * 2 ** min(8, max(0, retry_count - 1)))
        now = time.time()
        return {'transport_retry_count': retry_count, 'retry_delay_seconds': round(delay, 3), 'next_retry_at': now + delay, 'max_transport_checkpoint_retries': max_retries}

    async def _persist_model_transport_checkpoint(self, *, node: WorkflowNode, run: WorkflowRun, error: Exception, opts: dict[str, Any], max_revision_rounds: int) -> None:
        """Persist provider exhaustion as a platform-owned resumable stop."""
        run_state = RunState(run.project_path, run.id)
        saved_revision = run_state.revision_state(node.id)
        try:
            round_number = max(0, int(saved_revision.get('round') or 0))
        except (TypeError, ValueError):
            round_number = 0
        try:
            cycle = max(1, int(saved_revision.get('cycle') or 1))
        except (TypeError, ValueError):
            cycle = 1
        summary = self._exception_summary(error)
        retry_schedule = {"manual_resume_required": True}
        diagnostics = {'accepted': False, 'reason': 'model transport exhausted', 'summary': summary, 'issues': [summary], 'error_type': type(error).__name__, 'error_category': 'transport', 'retryable': True, 'transport_exhausted': True, 'intervention_kind': 'platform_repair', 'requires_human_decision': False, 'hard_limit': False, 'max_transport_attempts': 1, 'transport_attempt_scope': 'workflow_stage', **retry_schedule}
        run_state.set_revision_waiting(node.id, round_number=round_number, cycle=cycle, gate=diagnostics, artifact_signature=self._revision_artifact_signature(run.project_path, node.id, opts), artifact_owner_id=node.id, runtime_signature=self._revision_runtime_signature(run.project_path, node.id, opts))
        node.status = NodeStatus.IDLE
        node.error = None
        node.finished_at = time.time()
        await self._emit(run, 'node_platform_repair_required', {'node_id': node.id, 'name': node.name, 'owner_node_id': node.id, 'round': round_number, 'cycle': cycle, 'reason': diagnostics['reason'], 'summary': summary, 'issues': [summary], 'component_statuses': {}, **retry_schedule})
        await self._emit(run, 'node_revision_waiting', {'node_id': node.id, 'name': node.name, 'round': round_number, 'cycle': cycle, 'max_revision_rounds': max_revision_rounds, **diagnostics})

    @staticmethod
    def _is_transport_revision_checkpoint(revision: dict[str, Any]) -> bool:
        """Whether an unchanged checkpoint is safe to retry.
    
            A transport interruption stores the artifact fingerprint after the
            last partial attempt. Equality with that fingerprint is therefore
            expected and is not proof that the researcher made no progress.
            Deterministic quality/no-progress checkpoints return False so their
            anti-loop guard remains active.
            """
        if not isinstance(revision, dict):
            return False
        last_gate = revision.get('last_gate') if isinstance(revision.get('last_gate'), dict) else {}
        if revision.get('transport_exhausted') is True:
            return True
        sources = (revision, last_gate)
        categories = {str(source.get('error_category') or '').strip().casefold() for source in sources}
        if any((category in {'transport', 'network', 'provider_transport', 'model_transport'} for category in categories)):
            return True
        reasons = ' '.join((str(source.get(key) or '') for source in sources for key in ('reason', 'summary', 'error_type'))).casefold()
        return any((marker in reasons for marker in ('revision execution interrupted', 'model transport exhausted', 'model request timeout', 'api request timeout', 'stream stalled', 'incomplete chunked read', 'peer closed connection')))

    @staticmethod
    def _is_platform_repair_revision_checkpoint(revision: dict[str, Any]) -> bool:
        """Allow validation-only resume for an explicitly classified platform stop.
    
            The unchanged-artifact guard protects researcher-decision checkpoints
            from replaying the same model loop. A platform-owned stop is different:
            the artifact may already be valid after a deterministic repair, or the
            validator/runtime may have been fixed independently. Revalidation must
            therefore be possible without asking the researcher to edit a file.
    
            Current checkpoints persist the classification at the top level.
            Nested gate diagnostics provide context but never define ownership.
            """
        if not isinstance(revision, dict):
            return False
        last_gate = revision.get('last_gate') if isinstance(revision.get('last_gate'), dict) else {}
        if revision.get('requires_human_decision') is True or last_gate.get('requires_human_decision') is True:
            return False
        top_level_platform = str(revision.get('intervention_kind') or '').strip().casefold() == 'platform_repair'
        if top_level_platform:
            return revision.get('requires_human_decision') is not True
        return False

    @staticmethod
    def _is_terminal_revision_checkpoint(revision: dict[str, Any]) -> bool:
        """Return whether a bounded revision stop requires new evidence/input."""
        if not isinstance(revision, dict):
            return False
        last_gate = revision.get('last_gate') if isinstance(revision.get('last_gate'), dict) else {}
        terminal_stop_flags = ('hard_limit', 'stopped_for_no_progress', 'stopped_for_deterministic_stage', 'stopped_for_managed_stage')
        return any((bool(source.get(flag)) for source in (revision, last_gate) for flag in terminal_stop_flags))

    @classmethod
    def _platform_checkpoint_is_auto_recoverable(cls, revision: dict[str, Any]) -> bool:
        """Select platform-owned checkpoints for one fresh bounded cycle.
    
            Eligibility is intentionally structural. A platform checkpoint must
            not become non-recoverable merely because a validator or renderer
            changed its human-readable wording. Provider exhaustion and explicit
            researcher choices remain excluded: immediate replay cannot repair a
            dead network, and a loop must never answer a hypothesis, ethics, data
            access, or budget decision for the researcher.
            """
        if not cls._is_platform_repair_revision_checkpoint(revision):
            return False
        if cls._is_transport_revision_checkpoint(revision):
            return False
        if cls._is_terminal_revision_checkpoint(revision):
            return False
        last_gate = revision.get('last_gate') if isinstance(revision.get('last_gate'), dict) else {}
        if revision.get('requires_human_decision') is True or last_gate.get('requires_human_decision') is True or str(revision.get('intervention_kind') or last_gate.get('intervention_kind') or '').strip().casefold() == 'researcher_decision':
            return False
        return True

    @staticmethod
    def _exception_summary(exc: Exception) -> str:
        """Produce a non-empty exception summary for persisted/UI diagnostics."""
        message = str(exc).strip()
        if not message:
            message = '(no exception message was provided)'
        return f'{type(exc).__name__}: {message}'[:2000]

    def _build_gate_revision_instruction(self, node: WorkflowNode, diagnostics: dict, round_number: int, cycle: int, user_feedback: str='') -> str:
        findings = [item for item in diagnostics.get('findings', []) if isinstance(item, dict)]
        repair_tasks: list[str] = []
        for index, finding in enumerate(findings[:20], start=1):
            finding_id = str(finding.get('id') or f'ISSUE-{index}')
            message = str(finding.get('message') or finding.get('plain_message') or 'Resolve the reported gate failure.')
            owner = str(finding.get('owner_node') or node.id)
            targets = ', '.join((str(item) for item in finding.get('target_files', [])[:8])) or '(infer from the canonical artifact contract)'
            assets = ', '.join((str(item) for item in finding.get('asset_ids', [])[:8]))
            remediation = str(finding.get('remediation') or '').strip()
            repair_tasks.append(f'{index}. [{finding_id}] {message}\n   Owner: {owner}; target files: {targets}' + (f'; semantic assets: {assets}' if assets else '') + (f'\n   Required repair: {remediation}' if remediation else ''))
        if not repair_tasks:
            repair_tasks = [f'{index}. {item}' for index, item in enumerate(diagnostics.get('issues', [])[:20], start=1)]
        issue_lines = '\n'.join(repair_tasks) or '1. Re-read the canonical artifacts and resolve the reported gate failure.'
        scope = diagnostics.get('repair_scope')
        scope = scope if isinstance(scope, dict) else {}
        scope_text = '\nRepair scope: ' + json.dumps(scope, ensure_ascii=False, sort_keys=True) if scope else ''
        progress = diagnostics.get('revision_progress')
        progress = progress if isinstance(progress, dict) else {}
        progress_text = f"\nPrevious attempt: resolved={progress.get('resolved_finding_ids', [])}; new={progress.get('new_finding_ids', [])}; target_changed={bool(progress.get('target_changed'))}; consecutive_no_progress={int(progress.get('consecutive_no_progress') or 0)}." if progress else ''
        score_text = ''
        if diagnostics.get('score') is not None:
            score_text = f"\nCurrent score: {diagnostics.get('score')}; required threshold: {diagnostics.get('threshold')}."
        report_text = f"\nMachine-readable report: {diagnostics['report_path']}" if diagnostics.get('report_path') else ''
        feedback_text = '\n\nResearcher feedback (higher priority than optional stylistic choices):\n' + user_feedback.strip() if user_feedback.strip() else ''
        return f"Acceptance-gate remediation round {round_number}, cycle {cycle}, for node {node.id}.\n\nThe node produced artifacts, but the independent gate did not accept them.\nReason: {diagnostics.get('reason') or 'acceptance gate failed'}\nSummary: {diagnostics.get('summary') or '(none)'}{score_text}{report_text}{scope_text}{progress_text}\n\nMandatory targeted repairs:\n{issue_lines}\n\nRevise the existing canonical project artifacts in place, then verify them. Preserve the\ndeclared research objective and accepted upstream artifacts. Do not lower or bypass the\ngate, delete contrary evidence, fabricate citations/metrics, or turn planned/demo values\ninto scientific evidence. If evidence is genuinely unavailable, encode an explicit\nunsupported/pending claim and add the concrete experiment needed to resolve it.\nDo not merely explain what should change: use the available tools to make the changes.\nEdit the listed targets first. Do not regenerate unrelated figures, tables, sections, or\nwhole directories merely because they belong to the same workflow node.{feedback_text}\n"
