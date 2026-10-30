"""Separate reviewer file locations from exact producer write targets."""

from pathlib import Path
import re


def _file_owner_location(root: Path, message: str) -> str:
    """Resolve an explicit file in owner position; retain entry selectors as evidence."""
    owner = re.search(r'\[owner\s*=\s*([^\]]+)\]', message, re.I)
    target = re.search(r'\[target\s*=\s*([^\]]+)\]', message, re.I)
    if not owner or not target:
        return message
    value = owner[1].strip().replace('\\', '/')
    if '..' in Path(value).parts:
        return message
    path = root / value
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        return message
    if path.resolve().relative_to(root.resolve()).as_posix() != value:
        return message
    if value == 'literature/references.bib':
        node = 'lit'
    elif value == 'paper/references.bib' or (value.startswith('paper/sections/') and value.endswith('.tex')):
        node = 'paper'
    elif value.startswith(('experiments/src/', 'experiments/configs/')):
        node = 'exp-design'
    else:
        return message
    # Do not reinterpret another existing file target as a selector.
    if '/' in target[1] or '\\' in target[1] or ':' in target[1]:
        return message
    selector = target[1].strip()
    message = re.sub(r'\[owner\s*=\s*[^\]]+\]', '[owner=' + node + ']', message, count=1, flags=re.I)
    message = re.sub(r'\[target\s*=\s*[^\]]+\]', '[target=' + value + ']', message, count=1, flags=re.I)
    return message + '\nReviewer evidence selector: ' + selector


def normalize_target_locations(root: Path, message: str) -> str:
    """Keep selectors as evidence, never as NTFS stream names or guessed files."""
    message = _file_owner_location(root, message)
    locations = []
    def target(match):
        values = re.split(r'[,;、\s]+', match.group(1).strip())
        normalized = []
        for value in values:
            value = value.replace('\\', '/')
            located = re.fullmatch(r'((?:paper|literature|experiments|figures)/[^:]+\.[A-Za-z0-9]+)(::?)([A-Za-z0-9_.-]+)', value)
            if located:
                path = root / located[1]
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
                    locations.append(value)
                    value = located[1]
            normalized.append(value)
        return '[target=' + ','.join(normalized) + ']'
    normalized = re.sub(r'\[target\s*=\s*([^\]]+)\]', target, message, flags=re.I)
    if locations:
        normalized += '\nReviewer evidence locations: ' + ', '.join(locations)
    return normalized
