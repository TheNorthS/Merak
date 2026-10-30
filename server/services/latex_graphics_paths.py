"""Resolve literal graphic references in document order without accepting shadowed files."""

import re
from pathlib import Path


def resolved_graphics(root: Path, document_dir: Path, text: str) -> list[Path]:
    """Honor graphicspath and extension order; external files cannot bind project evidence."""
    root = root.resolve()
    text = re.sub(r'(?m)(?<!\\)%.*$', '', text)
    commands = re.compile(
        r'\\graphicspath\s*\{((?:\{[^{}]*\}\s*)+)\}'
        r'|\\DeclareGraphicsExtensions\s*\{([^{}]+)\}'
        r'|\\includegraphics\*?(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}', re.I)
    directories, extensions, result = [], ['.pdf', '.png', '.jpg', '.jpeg', '.eps'], []
    for command in commands.finditer(text):
        paths, declared_extensions, reference = command.groups()
        if paths is not None:
            directories = [document_dir / item for item in re.findall(r'\{([^{}]*)\}', paths)]
        elif declared_extensions is not None:
            extensions = [value.strip() for value in declared_extensions.split(',') if value.strip()]
        else:
            found = _first_existing(document_dir, directories, extensions, reference.strip())
            if found is not None and found.is_relative_to(root):
                result.append(found)
    return result


def _first_existing(document_dir: Path, directories: list[Path], extensions: list[str], reference: str) -> Path | None:
    raw = Path(reference)
    names = [raw] if raw.suffix else [raw.with_suffix(ext) for ext in extensions]
    for name in names:
        for directory in [document_dir, *directories]:
            candidate = directory / name
            if candidate.is_file():
                return candidate.resolve()
    return None
