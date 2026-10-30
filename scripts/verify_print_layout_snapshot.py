"""Authorized local print-layout QA in an independent copy; no models or science writes."""

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


def _protected(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for name in ('ideas', 'literature', 'experiments', 'figures')
            for path in (root / name).rglob('*') if path.is_file()}


async def _verify(root: Path, do_compile: bool) -> dict:
    from scripts.verify_live_remaining_snapshot import install_write_guard
    from scripts.live_snapshot_compilation import restricted_snapshot_compilation
    install_write_guard(root)
    from server.services.paper_print_repair import compile_print_verified_paper, prepare_print_figures
    from server.services.paper_print_projection import validate_print_projection
    from server.services.paper_compiler import paper_compiler
    before = _protected(root)
    try:
        if do_compile:
            with restricted_snapshot_compilation(root):
                result = await compile_print_verified_paper(paper_compiler, root)
            verdict = {'compile_success': result.success, 'pages': result.pages,
                       'pdf_path': result.pdf_path, 'errors': [item.message for item in result.errors]}
        else:
            packets = await prepare_print_figures(root)
            verdict = {'derived_assets': [row['asset_id'] for row in packets],
                       'projection_issues': validate_print_projection(root)}
    except Exception as error:
        verdict = {'error_type': type(error).__name__, 'error': str(error)}
        if hasattr(error, 'gate_details'):
            verdict['details'] = error.gate_details()
    verdict.update({'protected_inputs_unchanged': before == _protected(root),
                    'model_invoked': False, 'root': str(root)})
    from server.utils.atomic_write import atomic_write_json
    atomic_write_json(root / 'PRINT_LAYOUT_QA.json', verdict)
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--compile', action='store_true', help='Explicitly authorized local artifact compilation')
    options = parser.parse_args()
    source = options.source.resolve(strict=True)
    if (not source.is_relative_to(REPOSITORY) or source == REPOSITORY
            or not (source / 'paper/main.tex').is_file()):
        raise ValueError('Print QA source must be an existing independent project copy in this workspace')
    root = Path(tempfile.mkdtemp(prefix='print-layout-smoke-', dir=REPOSITORY)).resolve()
    shutil.copytree(source, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('qa-pages', 'paper-previews', '.candidate-*'))
    os.chdir(root)
    os.environ.update({'PYTHONDONTWRITEBYTECODE': '1', 'MPLCONFIGDIR': str(root / '.mpl-cache')})
    verdict = asyncio.run(_verify(root, options.compile))
    print(json.dumps(verdict, ensure_ascii=False), flush=True)
    return int(bool(verdict.get('error') or verdict.get('errors') or verdict.get('projection_issues')
                    or verdict.get('protected_inputs_unchanged') is not True))


if __name__ == '__main__':
    raise SystemExit(main())
