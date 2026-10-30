"""Exact source-bound print variants; reviewed science and original sources stay frozen.

Derived graphics and explicitly bound risk captions share one deterministic
paper-side transformation. All other authored bytes remain immutable.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json
from .latex_bundle import GRAPHIC_EXTENSIONS, _bases, _reachable_sources, _resolve, _tex_text


RECEIPT = 'paper/derived-figures/PRINT_PROJECTION.json'
_GRAPHIC = re.compile(r'(\\includegraphics\*?(?:\s*\[[^]]*\])?\s*\{)([^{}]+)(\})')
_INPUT = re.compile(r'(\\(?:input|include|subfile)\s*\{)([^{}]+)(\})')


def _local(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root):
        raise ValueError('Print projection cannot leave its project')
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _graphic_bases(root: Path, source: Path, sources: dict[Path, str]) -> list[Path]:
    bases = _bases(source, root / 'paper', root)
    for text in sources.values():
        for block in re.findall(r'\\graphicspath\s*\{((?:\{[^}]*\}\s*)+)\}', text):
            for raw in re.findall(r'\{([^}]*)\}', block):
                for base in (root / 'paper', source.parent):
                    candidate = (base / raw).resolve()
                    if candidate.is_relative_to(root):
                        bases.append(candidate)
    return list(dict.fromkeys(bases))


def _transform_sources(root: Path, sources: dict[Path, str], graphics: dict[Path, Path],
                       packets: list[dict[str, Any]] | None = None) -> dict[Path, str]:
    """Change bound graphics/risk captions and includes; preserve all other bytes."""
    from .paper_presentation_caption import caption_contracts, project_source_captions

    captions, used = caption_contracts(root, packets or []), {}
    changed: dict[Path, str] = {}
    for source, text in sources.items():
        bases = _graphic_bases(root, source, sources)
        def graphic(match: re.Match[str]) -> str:
            original = _resolve(match.group(2), bases, root, GRAPHIC_EXTENSIONS)
            replacement = graphics.get(original)
            if replacement is None:
                return match.group()
            return match.group(1) + replacement.relative_to(root / 'paper').as_posix() + match.group(3)
        result = project_source_captions(text, captions, graphics,
            lambda raw: _resolve(raw, bases, root, GRAPHIC_EXTENSIONS), used)
        result = _GRAPHIC.sub(graphic, result)
        if result != text:
            changed[source] = result
    if any(used.get(path) != 1 for path in captions):
        raise ValueError('Risk caption has no unique reachable exact public figure float')
    # Always resolve authored references in their original context, not an
    # intermediate derived path whose file may not have been committed yet.
    base_text = {source: changed.get(source, original) for source, original in sources.items()}
    for _ in range(len(sources) + 1):
        before = dict(changed)
        for source, original in sources.items():
            result = _project_includes(root, source, base_text[source], changed)
            if result != original:
                changed[source] = result
        if changed == before:
            return changed
    raise ValueError('Print projection include graph did not converge')


def _project_includes(root: Path, source: Path, text: str, changed: dict[Path, str]) -> str:
    """Preserve each resolved input identity under the actual paper compiler cwd."""
    from .paper_presentation_caption import _comment_mask

    paper = root / 'paper'
    result, cursor = [], 0
    for match in _INPUT.finditer(_comment_mask(text)):
        result.append(text[cursor:match.start()])
        child = _resolve(match.group(2), _bases(source, paper, root), root, ('.tex', ''))
        if child is None:
            # Unknown references remain the normal compiler's responsibility.
            result.append(text[match.start():match.end()])
        else:
            target = _copy_path(root, child) if child in changed else child
            relative = (target.relative_to(paper).as_posix() if target.is_relative_to(paper)
                        else '../' + target.relative_to(root).as_posix())
            result.append(match.group(1) + relative + match.group(3))
        cursor = match.end()
    result.append(text[cursor:])
    return ''.join(result)


def _copy_path(root: Path, source: Path) -> Path:
    if source == root / 'paper/main.tex':
        return source
    if not source.is_relative_to(root / 'paper') or source.suffix != '.tex':
        raise ValueError('Print overlays require a local paper TeX source')
    output = (root / 'paper/derived-figures/tex' / source.relative_to(root / 'paper')).resolve()
    if not output.is_relative_to(root / 'paper/derived-figures'):
        raise ValueError('Print overlay output cannot follow an external directory link')
    return output


def install_print_projection(root: str | Path, packets: list[dict[str, Any]]) -> None:
    """Create derived TeX and switch the generated entrypoint, never source sections."""
    root = Path(root).resolve()
    main = root / 'paper/main.tex'
    if (root / RECEIPT).exists():
        restore_print_entrypoint(root)
    reachable = _reachable_sources(main, root / 'paper', root)
    sources = {path: path.read_text(encoding='utf-8-sig') for path in reachable if path.suffix == '.tex'}
    graphics = {_local(root, item['original_path']): _local(root, item['output_path']) for item in packets}
    if len(graphics) != len(packets):
        raise ValueError('Duplicate original graphic in print projection')
    changed = _transform_sources(root, sources, graphics, packets)
    if main not in changed:
        raise ValueError('Print projection did not reach the manuscript entrypoint')
    backup = _local(root, 'paper/derived-figures/ORIGINAL_MAIN.tex')
    outputs = {backup: main.read_bytes()}
    records = []
    for source, text in sorted(changed.items()):
        destination = _copy_path(root, source)
        outputs[destination] = text.encode('utf-8')
        records.append({'original_path': source.relative_to(root).as_posix(),
                        'original_sha256': hashlib.sha256(sources[source].encode()).hexdigest(),
                        'output_path': destination.relative_to(root).as_posix(),
                        'output_sha256': hashlib.sha256(outputs[destination]).hexdigest()})
    receipt = {'schema': 1, 'packets': packets, 'sources': records,
               'source_context': [{'path': path.relative_to(root).as_posix(),
                                   'sha256': hashlib.sha256(text.encode()).hexdigest()}
                                  for path, text in sorted(sources.items())],
               'original_main_path': backup.relative_to(root).as_posix(),
               'original_main_sha256': hashlib.sha256(outputs[backup]).hexdigest()}
    _commit_projection(root, outputs, receipt)


def _commit_projection(root: Path, outputs: dict[Path, bytes], receipt: dict[str, Any]) -> None:
    record = _local(root, RECEIPT)
    before = {path: path.read_bytes() if path.is_file() else None for path in (*outputs, record)}
    try:
        # Entry point is the last artifact switched, followed by its receipt.
        for path, content in sorted(outputs.items(), key=lambda item: item[0] == root / 'paper/main.tex'):
            atomic_write_bytes(path, content)
        atomic_write_json(record, receipt)
    except BaseException:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, content)
        raise


def _payload(root: Path) -> dict[str, Any] | None:
    if not (root / RECEIPT).exists():
        return None
    payload = json.loads((root / RECEIPT).read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('schema') != 1:
        raise ValueError('Unsupported print projection receipt')
    return payload


def validate_print_projection(root: str | Path) -> list[str]:
    """A hash-only forgery cannot change prose or redirect graphics to arbitrary pixels."""
    root = Path(root).resolve()
    try:
        if 'derived-figures/' not in _tex_text(root / 'paper/main.tex'):
            return []
        payload = _payload(root)
        if payload is None:
            raise ValueError('Projected entrypoint has no print projection receipt')
        from .paper_derived_figure_rendering import validate_derived_figure
        packets = payload['packets']
        if not packets or not isinstance(packets, list):
            raise ValueError('Print projection has no bound graphic packet')
        for packet in packets:
            issues = validate_derived_figure(root, packet)
            if issues:
                raise ValueError('; '.join(issues))
        backup = _local(root, payload['original_main_path'])
        if _sha(backup) != payload['original_main_sha256']:
            raise ValueError('Original print entrypoint binding is stale')
        if 'derived-figures/' in _tex_text(backup):
            raise ValueError('Print projection cannot chain unreviewed source overlays')
        originals = {_local(root, row['original_path']): row for row in payload['sources']}
        if len(originals) != len(payload['sources']):
            raise ValueError('Duplicate print source bindings')
        main = root / 'paper/main.tex'
        context = {_local(root, row['path']): row for row in payload['source_context']}
        if len(context) != len(payload['source_context']) or not set(originals) <= set(context):
            raise ValueError('Print context closure is incomplete or duplicated')
        reachable = _reachable_sources(backup, root / 'paper', root)
        actual = {main if path == backup else path for path in reachable if path.suffix == '.tex'}
        if actual != set(context):
            raise ValueError('Print source context differs from reachable original sources')
        source_text = {path: (backup if path == main else path).read_text(encoding='utf-8-sig') for path in context}
        for path, text in source_text.items():
            if hashlib.sha256(text.encode()).hexdigest() != context[path]['sha256']:
                raise ValueError('Reviewed manuscript source changed after print projection')
        graphics = {_local(root, item['original_path']): _local(root, item['output_path']) for item in packets}
        if len(graphics) != len(packets):
            raise ValueError('Duplicate projected figure identity')
        expected = _transform_sources(root, source_text, graphics, packets)
        if set(expected) != set(originals):
            raise ValueError('Print source closure differs from its deterministic transform')
        for source, text in expected.items():
            destination = _copy_path(root, source)
            row = originals[source]
            if (destination != _local(root, row['output_path']) or _sha(destination) != row['output_sha256']
                    or destination.read_text(encoding='utf-8-sig') != text):
                raise ValueError('Print overlay differs from the exact graphics-only transform and source-bound caption projection')
        return []
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return [f'Publication print projection is invalid: {error}']


def restore_print_entrypoint(root: str | Path) -> None:
    """Reassembly may replace main.tex; never restore an unbound or edited entrypoint."""
    root = Path(root).resolve()
    if 'derived-figures/' not in _tex_text(root / 'paper/main.tex'):
        return
    payload = _payload(root)
    if payload is None:
        return
    main = root / 'paper/main.tex'
    record = next((row for row in payload['sources'] if row['original_path'] == 'paper/main.tex'), None)
    backup = _local(root, payload['original_main_path'])
    if record is None or _sha(backup) != payload['original_main_sha256']:
        raise ValueError('Cannot restore an unbound print entrypoint')
    current = _sha(main)
    if current == record['output_sha256']:
        atomic_write_bytes(main, backup.read_bytes())
    elif current != record['original_sha256']:
        # A fresh deterministic assembly is allowed; it will bind a new projection.
        if 'derived-figures/tex/' in _tex_text(main):
            raise ValueError('Cannot restore a modified projected entrypoint')


def original_print_inputs(root: str | Path) -> set[str]:
    """Validated overlays retain the exact authored section inclusion contract."""
    root = Path(root).resolve()
    payload = _payload(root)
    if payload is None:
        return set()
    issues = validate_print_projection(root)
    if issues:
        raise ValueError('; '.join(issues))
    backup = _local(root, payload['original_main_path'])
    return {match.group(2) for match in _INPUT.finditer(_tex_text(backup))}


def assembled_print_sha256(root: str | Path) -> str:
    """Compare reviewed assembly to its original, only after strict overlay validation."""
    root = Path(root).resolve()
    if 'derived-figures/' not in _tex_text(root / 'paper/main.tex'):
        return _sha(root / 'paper/main.tex')
    payload = _payload(root)
    if payload is None:
        raise ValueError('Projected entrypoint has no print projection receipt')
    issues = validate_print_projection(root)
    if issues:
        raise ValueError('; '.join(issues))
    return str(payload['original_main_sha256'])


def canonical_print_graphic(root: str | Path, graphic: Path) -> Path:
    """A verified paper-side graphic retains its original scientific asset identity."""
    root = Path(root).resolve()
    if not graphic.resolve().is_relative_to(root / 'paper/derived-figures'):
        return graphic.resolve()
    issues = validate_print_projection(root)
    if issues:
        raise ValueError('; '.join(issues))
    payload = _payload(root)
    if payload is None:
        raise ValueError('Printed figure has no validated projection inventory')
    matches = [packet for packet in payload['packets'] if _local(root, packet['output_path']) == graphic.resolve()]
    if len(matches) != 1:
        raise ValueError('Printed figure has no unique current source identity')
    return _local(root, matches[0]['original_path'])
