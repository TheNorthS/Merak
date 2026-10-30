"""Split artifacts_b workflow responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class ArtifactsBExtraMixin:
    def _artifact_snapshot_issues(self, project_path: str, snapshot: Any) -> list[str]:
        """Compare every owned artifact against its recorded content binding.

        Semantic manifests intentionally ignore renderer-only metadata. A raw
        file snapshot still requires exact content equality, even for manifests.
        The aggregate workflow report is derived, not an owned node dependency.
        """
        if not isinstance(snapshot, dict) or not snapshot:
            return ['accepted phase has no content-bound artifact snapshot']
        root = Path(project_path).expanduser().resolve()
        issues: list[str] = []
        for key, expected in snapshot.items():
            if not isinstance(expected, dict):
                issues.append(f'invalid artifact snapshot entry: {key}')
                continue
            raw_path = Path(str(key))
            normalized_key = str(key).replace('\\', '/').strip('/').casefold()
            if normalized_key.endswith('.merak/research_workflow_contract.json'):
                continue
            target = raw_path if raw_path.is_absolute() else root / raw_path
            if expected.get('kind') == 'pdf_content':
                from ..services.pdf_content_snapshot import pdf_content_snapshot
                current = pdf_content_snapshot(target)
                if not expected.get('sha256') or current != expected:
                    issues.append(f'accepted PDF content changed: {key}')
                continue
            if expected.get('kind') == 'node_search_evidence':
                from ..services.search_evidence_snapshot import search_evidence_snapshot
                current = search_evidence_snapshot(target, str(expected.get('node_id') or ''))
                if not current['sha256'] or current != expected:
                    issues.append(f'accepted retrieval evidence changed: {key} owner={expected.get("node_id")}')
                continue
            if str(expected.get('kind') or '') == 'semantic_manifest':
                current = self._semantic_manifest_snapshot_state(target)
                expected_hash = str(expected.get('sha256') or '').strip().casefold()
                current_hash = str(current.get('sha256') or '').strip().casefold()
                if not expected_hash or not current_hash:
                    issues.append(f'accepted semantic artifact missing or invalid: {key}')
                elif expected_hash != current_hash:
                    issues.append(f'accepted semantic artifact changed: {key}')
                continue
            current = artifact_state(target, exclude=expected.get('excluded') or [])
            if not artifact_state_equal(expected, current):
                issues.append(f'accepted artifact changed: {key}')
        return issues

    @classmethod
    def _stable_revision_json(cls, value: Any) -> Any:
        """Remove attempt/timing metadata without erasing scientific run IDs."""
        volatile = {'updated_at', 'created_at', 'generated_at', 'evaluated_at', 'saved_at', 'waiting_since', 'timestamp', 'modified_at', 'reviewed_at', 'directed_updated_at', 'started_at', 'finished_at', 'compile_time_ms', 'duration_ms', 'elapsed_ms', 'mtime', 'mtime_ns', 'attempt_count', 'retry_count', 'transport_retry_count', 'revision_attempts', 'directed_attempts', 'last_attempt_at', 'next_retry_at'}
        if isinstance(value, dict):
            stable: dict[str, Any] = {}
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
                normalized = str(key).casefold()
                if normalized in volatile or normalized.endswith(('_attempt_count', '_retry_count')) or (normalized == 'attempts' and (not isinstance(item, (list, dict)))):
                    continue
                stable[str(key)] = cls._stable_revision_json(item)
            return stable
        if isinstance(value, list):
            return [cls._stable_revision_json(item) for item in value]
        return value

    @classmethod
    def _revision_file_bytes(cls, path: Path) -> bytes:
        try:
            if path.suffix.casefold() == '.json':
                payload = json.loads(path.read_text(encoding='utf-8-sig', errors='replace'))
                if path.name.casefold() in {'simulation_manifest.json', 'planned_result_manifest.json'}:
                    from ..services.paper_artifacts import simulation_manifest_semantic_payload
                    payload = simulation_manifest_semantic_payload(payload)
                return json.dumps(cls._stable_revision_json(payload), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
            return path.read_bytes()
        except (OSError, UnicodeError, json.JSONDecodeError):
            return b'<unreadable>'

    @staticmethod
    def _generated_revision_report(relative: Path) -> bool:
        normalized = relative.as_posix().strip('/').casefold()
        return bool(normalized == '.merak/quality' or normalized.startswith('.merak/quality/') or normalized.startswith('review-stage/') or normalized.startswith('audit-results/') or (normalized == 'paper/proof_audit.json') or normalized.endswith('-risk.json') or normalized.endswith('workflow_risk_snapshot.json'))

    def _revision_scope_signature(self, project_path: str, node_id: str, diagnostics: dict[str, Any], options: Optional[dict[str, Any]]=None) -> str:
        """Fingerprint only artifacts implicated by the current structured findings."""
        root = Path(project_path).expanduser().resolve()
        scope = diagnostics.get('repair_scope')
        scope = scope if isinstance(scope, dict) else {}
        raw_paths = [str(item).strip() for item in scope.get('target_files') or [] if str(item).strip()]
        asset_ids = {str(item).strip() for item in scope.get('asset_ids') or [] if str(item).strip()}
    
        def load_json(path: Path) -> dict[str, Any]:
            try:
                value = json.loads(path.read_text(encoding='utf-8-sig', errors='replace'))
            except (OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}
        if asset_ids:
            plan = load_json(root / 'figures' / 'SCIENTIFIC_ASSET_PLAN.json')
            for asset in plan.get('assets', []):
                if not isinstance(asset, dict) or str(asset.get('id') or '') not in asset_ids:
                    continue
                raw_paths.extend((str(asset.get(key) or '').strip() for key in ('data_path', 'output_path', 'source_path') if str(asset.get(key) or '').strip()))
                raw_paths.extend((str(path) for path in self._manifest_dependency_paths(root, asset)))
            manifest = load_json(root / 'figures' / 'FIGURE_MANIFEST.json')
            for item in manifest.get('figures', []):
                if not isinstance(item, dict):
                    continue
                metadata = item.get('metadata')
                metadata = metadata if isinstance(metadata, dict) else {}
                semantic_key = str(metadata.get('semantic_key') or item.get('semantic_key') or '')
                if semantic_key not in asset_ids:
                    continue
                raw_paths.extend((str(item.get(key) or '').strip() for key in ('source_path', 'output_path', 'preview_path') if str(item.get(key) or '').strip()))
                raw_paths.extend((str(path) for path in self._manifest_dependency_paths(root, item)))
        paths: list[Path] = []
        seen: set[str] = set()
        for raw in raw_paths:
            normalized = raw.replace('\\', '/')
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = root / Path(normalized)
            try:
                resolved = candidate.resolve()
                relative = resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if self._generated_revision_report(relative):
                continue
            marker = str(resolved).casefold()
            if marker in seen:
                continue
            seen.add(marker)
            paths.append(resolved)
        if not paths:
            return self._revision_artifact_signature(project_path, node_id, options)
        digest = hashlib.sha256()
        digest.update(f'revision-scope:v1:{node_id}'.encode('utf-8'))
        for path in sorted(paths, key=lambda item: item.as_posix().casefold()):
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = str(path)
            digest.update(relative.encode('utf-8', errors='replace'))
            if path.is_file():
                digest.update(hashlib.sha256(self._revision_file_bytes(path)).digest())
            elif path.is_dir():
                for child in sorted((item for item in path.rglob('*') if item.is_file())):
                    digest.update(child.relative_to(path).as_posix().encode('utf-8'))
                    digest.update(hashlib.sha256(self._revision_file_bytes(child)).digest())
            else:
                digest.update(b'<missing>')
        return f'revision-scope:{digest.hexdigest()[:24]}'

    def _canonical_output_contract_prompt(self, node_id: str, project_path: str) -> str:
        """Use the shared producer contract without post-write path adaptation."""
        from ..services.artifact_contract import render_artifact_contract

        return render_artifact_contract(project_path, node_id)


    def _artifact_has_content(self, path: Path, since: Optional[float]=None) -> bool:
        fresh_after = since - 1.0 if since else None
        if path.is_file():
            stat = path.stat()
            return stat.st_size > 0 and (fresh_after is None or stat.st_mtime >= fresh_after)
        if path.is_dir():
            checked = 0
            for child in path.rglob('*'):
                if child.is_file():
                    checked += 1
                    stat = child.stat()
                    if stat.st_size > 0 and (fresh_after is None or stat.st_mtime >= fresh_after):
                        return True
                    if checked >= 200:
                        break
        return False

    def _artifact_check(self, paths: list[Path], since: Optional[float]=None, *, baseline: Optional[dict[str, dict[str, Any]]]=None, project_path: str='', input_baseline: Optional[dict[str, Any]]=None) -> tuple[bool, list[str]]:
        missing = [str(path) for path in paths if not self._artifact_has_content(path)]
        if missing:
            return (False, missing)
        if baseline is not None and project_path and paths:
            unchanged_undeclared = [path for path in paths if not self._artifact_changed_from_baseline(project_path, path, baseline) and (not workflow_input_service.covers(project_path, input_baseline, path))]
            changed_or_declared = [path for path in paths if path not in unchanged_undeclared]
            if changed_or_declared:
                return (True, [])
            return (False, ['no canonical output changed by content during this node attempt: ' + ', '.join((str(path) for path in paths)) + '; at least one non-input artifact must change while all required artifacts remain valid'])
        if since is not None and paths and (not any((self._artifact_has_content(path, since=since) for path in paths))):
            return (False, ['no canonical artifact changed after the node started; preserve valid files and modify the artifact implicated by the gate'])
        return (True, [])

    def _experiment_code_integrity_gate(self, project_path: str) -> dict[str, Any]:
        """Perform cheap static checks before any experiment claim can proceed."""
        root = Path(project_path).expanduser().resolve()
        source_root = root / 'experiments' / 'src'
        config_root = root / 'experiments' / 'configs'
        issues: list[str] = []
        python_files = sorted((path for path in source_root.rglob('*.py') if path.is_file() and '__pycache__' not in path.parts)) if source_root.is_dir() else []
        for path in python_files:
            try:
                text = path.read_text(encoding='utf-8-sig', errors='strict')
                ast.parse(text, filename=str(path))
            except (OSError, UnicodeError) as exc:
                issues.append(f'{path.relative_to(root).as_posix()}: cannot read source: {exc}')
            except SyntaxError as exc:
                location = f'line {exc.lineno}' if exc.lineno else 'unknown line'
                detail = str(exc.msg or 'syntax error').strip()
                issues.append(f'{path.relative_to(root).as_posix()}: Python syntax error at {location}: {detail}')
        try:
            import yaml
        except ImportError:
            yaml = None
        config_files = sorted([*config_root.glob('*.yaml'), *config_root.glob('*.yml'), *config_root.glob('*.json')]) if config_root.is_dir() else []
        for path in config_files:
            try:
                text = path.read_text(encoding='utf-8-sig', errors='strict')
                if path.suffix.lower() == '.json':
                    json.loads(text)
                elif yaml is not None:
                    yaml.safe_load(text)
                elif not text.strip():
                    raise ValueError('empty configuration')
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                issues.append(f'{path.relative_to(root).as_posix()}: invalid configuration: {exc}')
            except Exception as exc:
                issues.append(f'{path.relative_to(root).as_posix()}: configuration parser error: {exc}')
        run_spec = root / 'experiments' / 'RUN_SPEC.json'
        if run_spec.is_file():
            try:
                json.loads(run_spec.read_text(encoding='utf-8-sig', errors='strict'))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                issues.append(f'experiments/RUN_SPEC.json: invalid JSON: {exc}')
        return {'passed': not issues, 'issues': issues, 'python_files_checked': [path.relative_to(root).as_posix() for path in python_files], 'config_files_checked': [path.relative_to(root).as_posix() for path in config_files]}

    def _verdict_id(self, prefix: str, artifacts: list[Path]) -> str:
        import hashlib
        digest = hashlib.sha256()
        digest.update(prefix.encode('utf-8'))
        for artifact in artifacts:
            path = Path(artifact)
            digest.update(str(path).encode('utf-8', errors='ignore'))
            if path.is_file():
                stat = path.stat()
                digest.update(f':{stat.st_size}:{stat.st_mtime_ns}'.encode('utf-8'))
            elif path.is_dir():
                checked = 0
                for child in sorted((item for item in path.rglob('*') if item.is_file()), key=lambda item: item.as_posix()):
                    try:
                        stat = child.stat()
                        relative = child.relative_to(path).as_posix()
                    except (OSError, ValueError):
                        continue
                    digest.update(f':{relative}:{stat.st_size}:{stat.st_mtime_ns}'.encode('utf-8', errors='ignore'))
                    checked += 1
                    if checked >= 2000:
                        digest.update(b':directory-scan-truncated')
                        break
        return f'{prefix}:{digest.hexdigest()[:16]}'

    def _exp_design_method_alignment_gate(self, run: WorkflowRun, research_direction: str) -> dict:
        """Validate the accepted idea against project-declared implementation evidence."""
        from ..services.experiment_implementation import experiment_implementation_service
        from ..services.method_contract import method_contract_service
        root = Path(run.project_path).resolve()
        selected = self._extract_selected_idea(root, '', research_direction)
        state = RunState(run.project_path, run.id).load() or {}
        novelty_details = state.get('phases', {}).get('novelty', {}).get('details', {})
        expected_idea_hash = str(novelty_details.get('selected_idea_contract_sha256') or '')
        evidence_mode = str(run.options.get('non_experiment_evidence_mode') or 'design_only').strip().casefold()
        allow_planned = run.options.get('run_experiment') is not True and evidence_mode != 'synthetic_preview'
        accepted, issues, details = method_contract_service.validate_method_contract(root, selected, expected_idea_sha256=expected_idea_hash, allow_planned=allow_planned)
        implementation_audit = experiment_implementation_service.audit(root)
        implementation_issues = [str(item.get('message') or '').strip() for item in implementation_audit.get('findings', []) if str(item.get('severity') or '').casefold() == 'blocker' and str(item.get('message') or '').strip()]
        issues = list(dict.fromkeys([*issues, *implementation_issues]))
        if implementation_audit.get('blocking'):
            accepted = False
        implementation_build: dict[str, Any] = {'applicable': False, 'blocking': False, 'status': 'not_requested', 'issues': []}
        blueprint_path = root / 'experiments' / 'IMPLEMENTATION_BLUEPRINT.json'
        build_path = root / 'experiments' / 'IMPLEMENTATION_BUILD.json'
        if blueprint_path.is_file() or build_path.is_file():
            from ..services.experiment_implementation_build import experiment_implementation_build_service
            implementation_build = experiment_implementation_build_service.audit(root, research_direction)
            build_issues = [str(item).strip() for item in implementation_build.get('issues', []) if str(item).strip()]
            issues = list(dict.fromkeys([*issues, *build_issues]))
            if implementation_build.get('blocking'):
                accepted = False
        implementation_pending = bool(details.get('implementation_pending'))
        component = {'label': '方法契约', 'applicable': True, 'passed': bool(accepted and (not issues)), 'summary': '实验设计已绑定冻结 Idea；代码实现明确待补，当前不作为实验证据。' if accepted and (not issues) and implementation_pending else '实现代码、配置和冻结 Idea 已对齐。' if accepted and (not issues) else '实现代码、配置或方法契约与冻结 Idea 尚未对齐。', 'issues': list(issues)}
        details = {**details, 'implementation_contract': component, 'implementation_integrity': implementation_audit, 'staged_implementation_build': implementation_build, 'allow_planned_implementation': allow_planned, 'evidence_mode': evidence_mode}
        if issues:
            return {'accepted': False, 'reason': 'accepted idea and implementation contract are misaligned', 'summary': '; '.join(issues[:8]), 'details': details}
        return {'accepted': bool(accepted), 'summary': f'Implementation evidence satisfies the accepted idea contract: {selected}.', 'details': details}
