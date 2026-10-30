"""Split artifacts_b workflow responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class ArtifactsBMixin:
    def _node_artifact_paths(self, node: WorkflowNode, run: WorkflowRun) -> list[Path]:
        paths = self._gate_requirements_for_node(run, node.id)
        if node.id == 'results' and run.options.get('run_experiment') is not True and (str(run.options.get('non_experiment_evidence_mode') or 'design_only').strip().casefold() == 'synthetic_preview'):
            root = Path(run.project_path).expanduser().resolve()
            paths.extend([root / 'experiments' / 'results' / 'analysis.md', root / 'experiments' / 'results' / 'simulated', root / 'experiments' / 'results' / 'simulated' / 'SIMULATION_MANIFEST.json'])
        return list(dict.fromkeys(paths))

    @staticmethod
    def _artifact_directory_exclusions(node_id: str) -> dict[str, list[str]]:
        """Exclude only files owned by a later workflow stage."""
        derived_plots = [f'aggregates/{name}.csv' for name in (
            'main_comparison', 'component_ablation', 'robustness_sensitivity', 'qualitative_evidence_matrix')]
        if node_id == 'exp-run':
            return {'experiments/results': ['analysis.md', 'templates', *derived_plots]}
        if node_id == 'results':
            return {'experiments/results': derived_plots}
        return {}

    def _snapshot_node_artifacts(self, node: WorkflowNode, run: WorkflowRun) -> dict[str, dict[str, Any]]:
        return snapshot_paths(run.project_path, self._node_artifact_paths(node, run), directory_exclusions=self._artifact_directory_exclusions(node.id))

    def _changed_nonempty_node_artifacts(self, node: WorkflowNode, run: WorkflowRun) -> list[Path]:
        """Return canonical owned artifacts whose content changed in this attempt."""
        baseline = node.artifact_baseline
        if not baseline:
            return []
        changed: list[Path] = []
        for artifact in self._node_artifact_paths(node, run):
            if not self._artifact_has_content(artifact):
                continue
            if self._artifact_changed_from_baseline(run.project_path, artifact, baseline):
                changed.append(artifact)
        return changed

    @staticmethod
    def _artifact_snapshot_key(project_path: str, path: Path) -> str:
        root = Path(project_path).expanduser().resolve()
        target = path.expanduser().resolve()
        try:
            return target.relative_to(root).as_posix()
        except ValueError:
            return str(target)

    @staticmethod
    def _semantic_manifest_snapshot_state(path: Path) -> dict[str, Any]:
        """Build a content binding for a JSON manifest's scientific projection."""
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {'kind': 'semantic_manifest', 'semantic_schema': 'simulation-manifest-v1', 'sha256': ''}
        if not isinstance(payload, dict):
            return {'kind': 'semantic_manifest', 'semantic_schema': 'simulation-manifest-v1', 'sha256': ''}
        from ..services.paper_artifacts import simulation_manifest_semantic_hash
        return {'kind': 'semantic_manifest', 'semantic_schema': 'simulation-manifest-v1', 'sha256': simulation_manifest_semantic_hash(payload)}

    def _artifact_changed_from_baseline(self, project_path: str, path: Path, baseline: dict[str, dict[str, Any]] | None) -> bool:
        if baseline is None:
            return False
        key = self._artifact_snapshot_key(project_path, path)
        previous = baseline.get(key)
        if previous is None:
            previous = {'kind': 'missing', 'sha256': '', 'size': 0, 'file_count': 0}
        return not artifact_state_equal(previous, artifact_state(path, exclude=previous.get('excluded') or []))

    @staticmethod
    def _project_artifact_reference(root: Path, raw: Any) -> Optional[Path]:
        value = str(raw or '').strip()
        if not value:
            return None
        candidate = Path(value).expanduser()
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        return candidate

    def _manifest_dependency_paths(self, root: Path, payload: Any) -> list[Path]:
        """Extract only path-valued fields that deterministic gates dereference."""
        scalar_keys = {'data_path', 'latex_path', 'output_path', 'source_path', 'preview_path', 'review_trace_path', 'layout_report_path', 'simulation_manifest_path', 'image2_verify_path', 'source_manifest_path', 'snapshot_path', 'pdf_path', 'trace_path', '_review_trace_path', 'log_path'}
        list_keys = {'source_data', 'page_preview_paths', 'contact_sheet_paths', 'artifact_paths', 'source_files', 'sources'}
        mapping_keys = {'rendered_variants', 'protocol_artifacts'}
        paths: list[Path] = []
    
        def add(raw: Any) -> None:
            candidate = self._project_artifact_reference(root, raw)
            if candidate is not None:
                paths.append(candidate)
    
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for raw_key, item in value.items():
                    key = str(raw_key).casefold()
                    if key in scalar_keys:
                        add(item)
                    elif key in list_keys and isinstance(item, list):
                        for child in item:
                            add(child)
                    elif key in mapping_keys and isinstance(item, dict):
                        for child in item.values():
                            add(child)
                    elif isinstance(item, (dict, list)):
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(payload)
        return paths

    def _bind_gate_artifact_snapshot(self, node: WorkflowNode, run: WorkflowRun, gate: dict[str, Any]) -> None:
        details = gate.setdefault('details', {})
        if not isinstance(details, dict):
            details = {}
            gate['details'] = details
        if node.id == 'results':
            from ..services.node_risk_audit import node_risk_audit_service
            analysis_build = node_risk_audit_service.bind_result_analysis_inputs(run.project_path, run.options)
            if analysis_build:
                details['analysis_build_path'] = 'experiments/results/ANALYSIS_BUILD.json'
                details['analysis_source_bundle_sha256'] = str(analysis_build.get('source_bundle_sha256') or '')
        requirements = self._gate_requirements_for_node(run, node.id)
        details['artifacts'] = [str(path) for path in requirements]
        if node.id == 'exp-run' and run.options.get('run_experiment') is True:
            details['artifact_snapshot'] = self._managed_experiment_artifact_snapshot(run, details)
            details['artifact_snapshot_mode'] = MANAGED_EXPERIMENT_SNAPSHOT_MODE
            details['artifact_snapshot_schema'] = 2
            details['artifact_snapshot_paths'] = list(details['artifact_snapshot'])
        else:
            snapshot_requirements = self._accepted_snapshot_paths(run, node.id, gate, requirements)
            details['artifact_snapshot'] = snapshot_paths(run.project_path, snapshot_requirements, directory_exclusions=self._artifact_directory_exclusions(node.id))
            if node.id == 'review':
                from ..services.pdf_content_snapshot import pdf_content_snapshot
                details['artifact_snapshot']['paper/main.pdf'] = pdf_content_snapshot(Path(run.project_path) / 'paper/main.pdf')
            if node.id in {'lit', 'novelty'}:
                from ..services.search_evidence_snapshot import search_evidence_snapshot
                key = 'literature/SEARCH_EVIDENCE.json'
                details['artifact_snapshot'][key] = search_evidence_snapshot(Path(run.project_path) / key, node.id)
            if node.id == 'exp-run' and run.options.get('run_experiment') is not True:
                planned_manifest = Path(run.project_path).expanduser().resolve() / 'experiments' / 'results' / 'templates' / 'PLANNED_RESULT_MANIFEST.json'
                manifest_key = self._artifact_snapshot_key(run.project_path, planned_manifest)
                details['artifact_snapshot'].pop(manifest_key, None)
                if planned_manifest.is_file():
                    details['artifact_snapshot'][manifest_key] = self._semantic_manifest_snapshot_state(planned_manifest)
            if node.id == 'results' and run.options.get('run_experiment') is not True and (str(run.options.get('non_experiment_evidence_mode') or 'design_only').strip().casefold() == 'synthetic_preview'):
                manifest_path = Path(run.project_path).expanduser().resolve() / 'experiments' / 'results' / 'simulated' / 'SIMULATION_MANIFEST.json'
                manifest_key = self._artifact_snapshot_key(run.project_path, manifest_path)
                details['artifact_snapshot'][manifest_key] = self._semantic_manifest_snapshot_state(manifest_path)
                details['artifact_snapshot_mode'] = SEMANTIC_RESULTS_SNAPSHOT_MODE
            details['artifact_snapshot_schema'] = 2
            details['artifact_snapshot_paths'] = [self._artifact_snapshot_key(run.project_path, path) for path in snapshot_requirements]
        details['input_baseline_snapshot_id'] = str(run.input_baseline.get('snapshot_id') or '')
        details['risk_audit_bound'] = True
        details['risk_audit_validator_signature'] = self._risk_audit_validator_signature(run.options)
        details['artifact_snapshot_bound_at'] = time.time()

    @staticmethod
    def _risk_audit_validator_signature(options: dict[str, Any]) -> str:
        from ..services.risk_validator_sources import risk_validator_source_paths
        root = Path(__file__).parents[1]
        sources = risk_validator_source_paths(root / 'services')
        digest = hashlib.sha256()
        digest.update(f'risk-audit-acceptance:v{RISK_AUDIT_ACCEPTANCE_CACHE_VERSION}'.encode())
        for path in sources:
            digest.update(path.name.encode())
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b'<missing>')
        volatile = {'audit_layer_timeout_seconds', 'checkpoint_timeout_seconds', 'max_revision_rounds', 'resume_run_id',
                    '_evidence_version_approval', '_manual_resume_id', '_manual_resume_node', '_resume_claim_token',
                    '_project_claim_token', '_project_claim_run_id'}
        stable_options = {str(key): value for key, value in sorted(dict(options or {}).items()) if str(key) not in volatile}
        digest.update(json.dumps(stable_options, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8'))
        return digest.hexdigest()

    def _managed_experiment_artifact_snapshot(self, run: WorkflowRun, details: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Bind immutable run contracts without rehashing multi-GB predictions."""
        root = Path(run.project_path).expanduser().resolve()
        paths: list[Path] = [root / 'experiments' / 'RUN_SPEC.json']
        raw_manifest_paths = details.get('manifest_paths')
        if not isinstance(raw_manifest_paths, list):
            raw_manifest_paths = []
        for raw in raw_manifest_paths:
            candidate = Path(str(raw or '')).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.is_file():
                paths.append(candidate.resolve())
        if len(paths) == 1:
            experiment_id = str(run.options.get('experiment_id') or f'workflow-{run.id}')
            runtime_root = root / '.merak' / 'experiments'
            if runtime_root.is_dir():
                paths.extend((path.resolve() for path in sorted(runtime_root.glob(f'{experiment_id[:56]}-seed-*/run.json')) if path.is_file()))
        large_evidence: list[dict[str, Any]] = []
        for manifest_path in list(paths):
            if manifest_path.name.casefold() != 'run.json':
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig', errors='replace'))
            except (OSError, json.JSONDecodeError):
                continue
            attempts = [item for item in manifest.get('attempts') or [] if isinstance(item, dict)]
            current_attempt = int(manifest.get('current_attempt') or 0)
            attempt = next((item for item in attempts if int(item.get('attempt') or 0) == current_attempt), {})
            artifacts = attempt.get('result_artifacts') or manifest.get('result_artifacts') or {}
            if not isinstance(artifacts, dict):
                continue
            for raw_path, facts in artifacts.items():
                candidate = self._project_artifact_reference(root, raw_path)
                if candidate is None or not candidate.is_file():
                    continue
                if candidate.stat().st_size <= MANAGED_EXPERIMENT_DIRECT_HASH_LIMIT_BYTES:
                    paths.append(candidate)
                else:
                    facts = facts if isinstance(facts, dict) else {}
                    large_evidence.append({'path': self._artifact_snapshot_key(run.project_path, candidate), 'bytes': candidate.stat().st_size, 'sha256': str(facts.get('sha256') or '')})
        unique: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            marker = str(path).casefold()
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(path)
        details['managed_evidence_manifests'] = [str(path) for path in unique if path.name.casefold() == 'run.json']
        details['managed_large_evidence_artifacts'] = large_evidence
        return snapshot_paths(root, unique)
