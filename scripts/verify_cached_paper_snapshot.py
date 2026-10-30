"""Reinspect existing authored paper in a new copy, with model invocation forbidden.

This exercises the real draft coordinator and paper consumer gates, not a
workflow acceptance transition. Original science, authorship, state and traces
remain immutable. Optional compilation is explicitly local and non-shell.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


class AuthorRequired(BaseException):
    def __init__(self, stage: str):
        self.stage = stage


def protected_files(root: Path) -> dict[str, str]:
    paths = [path for name in ('ideas', 'literature', 'experiments', 'figures', 'paper/sections',
                              '.merak/skill-invocations', '.merak/agent-sessions', '.merak/runs')
             for path in (root / name).rglob('*') if path.is_file()]
    paths.extend(root / relative for relative in ('paper/TITLE.txt', 'paper/CONTRIBUTION_BLUEPRINT.md'))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


async def _draft_existing(host, run, root, direction, author, event, revision_path: bool) -> dict:
    from server.services.paper_drafting import paper_drafting_service
    if not revision_path:
        return await paper_drafting_service.draft(root, direction, run.options, author, emit=event)
    from types import SimpleNamespace
    from server.workflows.revision_execution import _execute_paper_repairs
    gate = host._paper_acceptance_gate(str(root), require_staged=True, paper_options=run.options)
    if gate.get('accepted'):
        return await paper_drafting_service.draft(root, direction, run.options, author, emit=event)
    diagnostics = host._gate_revision_diagnostics(gate)
    scope = diagnostics.get('repair_scope') or {}
    targets = scope.get('target_files') or []
    staged = [path for path in targets if paper_drafting_service.stage_for_project_relative_target(path)]
    if not targets or len(staged) != len(targets):
        raise ValueError('No-model revision QA requires only canonical staged paper targets')
    results = []
    async def staged_draft(**arguments):
        result = await paper_drafting_service.draft(root, direction, run.options, author, emit=event,
                                                   revision_issues=arguments['revision_issues'])
        results.append(result)
        return json.dumps(result)
    adapter = SimpleNamespace(_execute_staged_paper=staged_draft)
    node = next(node for node in run.nodes if node.id == 'paper')
    await _execute_paper_repairs(adapter, node, run, diagnostics, direction, '', run.options,
                                 diagnostics.get('issues') or [], scope, targets, staged, [])
    if len(results) != 1:
        raise ValueError('No-model revision QA did not reach exactly one staged producer')
    return results[0]


async def verify(root: Path, run_id: str, do_compile: bool, revision_path: bool = False) -> dict:
    from scripts.verify_figure_snapshot import SnapshotEngine, snapshot_run
    from scripts.verify_live_remaining_snapshot import install_write_guard
    from scripts.local_acceptance_scope import local_reacceptance_scope
    from server.services.paper_drafting import paper_drafting_service
    install_write_guard(root)
    before = protected_files(root)
    run, config = snapshot_run(root, run_id)
    direction = str(config.get('direction') or '')
    host = SnapshotEngine()
    events = []
    async def author(stage, *_arguments):
        raise AuthorRequired(stage)
    async def event(kind, data):
        events.append({'event': kind, 'stage': data.get('stage_id'), 'passed': data.get('passed')})
    try:
        with local_reacceptance_scope():
            result = await _draft_existing(host, run, root, direction, author, event, revision_path)
            gate = host._paper_acceptance_gate(str(root), require_staged=True, paper_options=run.options)
        verdict = {'draft_completed': result.get('status') == 'completed',
                   'paper_source_gate_passed': gate.get('accepted') is True,
                   'issues': (gate.get('details') or {}).get('issues') or []}
        if not verdict['paper_source_gate_passed'] and not verdict['issues']:
            verdict['issues'] = [str(gate.get('summary') or gate.get('reason') or 'Paper source gate rejected the draft')]
        if do_compile and verdict['paper_source_gate_passed']:
            from scripts.live_snapshot_compilation import restricted_snapshot_compilation
            with restricted_snapshot_compilation(root):
                await host._ensure_paper_artifacts(run, 'No-model canonical paper revalidation', direction)
            final_gate = host._paper_acceptance_gate(str(root), require_staged=True,
                                                     require_page_budget=True, paper_options=run.options)
            build = json.loads((root / 'paper/PAPER_BUILD.json').read_text(encoding='utf-8-sig'))
            compiled = build.get('compile') or {}
            from server.services.paper_build_readiness import paper_build_issues
            build_issues, _bindings = paper_build_issues(root, build)
            verdict.update({'compile_success': compiled.get('success') is True, 'pages': compiled.get('pages'),
                            'pdf_path': compiled.get('pdf_path'), 'post_compile_final_gate_passed': final_gate.get('accepted') is True,
                            'paper_build_binding_passed': not build_issues,
                            'issues': [*((final_gate.get('details') or {}).get('issues') or []), *build_issues]})
            if not verdict['post_compile_final_gate_passed'] and not verdict['issues']:
                verdict['issues'] = [str(final_gate.get('summary') or final_gate.get('reason') or 'Final paper gate rejected the PDF')]
    except AuthorRequired as error:
        verdict = {'draft_completed': False, 'author_required_stage': error.stage, 'issues': ['Existing authored stage needs its author']}
    except Exception as error:
        verdict = {'draft_completed': False, 'error_type': type(error).__name__, 'issues': [str(error)]}
    verdict.update({'root': str(root), 'model_invoked': False, 'events': events,
                    'protected_files_unchanged': protected_files(root) == before})
    from server.utils.atomic_write import atomic_write_json
    atomic_write_json(root / 'CACHED_PAPER_QA.json', verdict)
    return verdict


def verified_result(result: dict, do_compile: bool) -> bool:
    flags = ('draft_completed', 'paper_source_gate_passed', 'protected_files_unchanged')
    if do_compile:
        flags += ('compile_success', 'post_compile_final_gate_passed', 'paper_build_binding_passed')
    return (all(result.get(flag) is True for flag in flags)
            and not result.get('issues') and not result.get('errors') and result.get('model_invoked') is False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--compile', action='store_true')
    parser.add_argument('--revision-path', action='store_true', help='Use actual outer target-file revision wrapping')
    options = parser.parse_args()
    source = options.source.resolve(strict=True)
    from scripts.live_snapshot_resume_validation import validate_copy_boundary
    if source == REPOSITORY or not source.is_relative_to(REPOSITORY) or not (source / 'paper/main.tex').is_file():
        raise ValueError('Cached-paper QA requires an existing independent project copy')
    validate_copy_boundary(source)
    root = Path(tempfile.mkdtemp(prefix='cached-paper-smoke-', dir=REPOSITORY)).resolve()
    shutil.copytree(source, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('paper-previews', 'qa-pages', '.candidate-*'))
    os.chdir(root)
    os.environ.update({'PYTHONDONTWRITEBYTECODE': '1', 'MPLCONFIGDIR': str(root / '.mpl-cache'),
                       'TEMP': str(root), 'TMP': str(root), 'openout_any': 'p', 'shell_escape': 'f'})
    tempfile.tempdir = str(root)
    result = asyncio.run(verify(root, options.run_id, options.compile, options.revision_path))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(not verified_result(result, options.compile))


if __name__ == '__main__':
    raise SystemExit(main())
