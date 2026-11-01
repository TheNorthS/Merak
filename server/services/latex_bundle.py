"""Hash the reachable, project-local inputs of a LaTeX entrypoint."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable


GRAPHIC_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def _tex_text(path: Path) -> str:
    from .paper_candidate_io import candidate_path
    path = candidate_path(path)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        match = re.search(r"(?<!\\)(?:\\\\)*%", line)
        lines.append(line[: match.start()] if match else line)
    return "\n".join(lines)


def _inside(path: Path, project_root: Path) -> bool:
    try:
        path.relative_to(project_root)
        return True
    except ValueError:
        return False


def _resolve(
    raw: str,
    bases: Iterable[Path],
    project_root: Path,
    suffixes: Iterable[str] = ("",),
) -> Path | None:
    from .paper_candidate_io import candidate_path
    value = str(raw or "").strip().strip("\"'")
    if not value or any(token in value for token in ("\\", "#", "{", "}")):
        return None
    relative = Path(value)
    for base in bases:
        unresolved = relative if relative.is_absolute() else base / relative
        candidates = (
            [unresolved]
            if relative.suffix
            else [unresolved.with_suffix(suffix) for suffix in suffixes]
        )
        for candidate in candidates:
            try:
                candidate = candidate.expanduser().resolve()
            except OSError:
                continue
            if (
                _inside(candidate, project_root)
                and candidate_path(candidate).is_file()
                and candidate_path(candidate).stat().st_size > 0
            ):
                return candidate
    return None


def _bases(source: Path, source_root: Path, project_root: Path) -> list[Path]:
    return list(dict.fromkeys((source.parent, source_root, project_root)))


def _reachable_sources(
    entrypoint: Path,
    source_root: Path,
    project_root: Path,
) -> set[Path]:
    from .paper_candidate_io import candidate_path
    reachable: set[Path] = set()
    queue = [entrypoint]
    while queue:
        source = queue.pop(0).resolve()
        if source in reachable or not candidate_path(source).is_file() or not _inside(source, project_root):
            continue
        reachable.add(source)
        text = _tex_text(source)
        bases = _bases(source, source_root, project_root)
        for raw in re.findall(
            r"\\(?:input|include|subfile)\s*\{([^}]+)\}", text, re.IGNORECASE
        ):
            dependency = _resolve(raw, bases, project_root, (".tex", ""))
            if dependency and dependency.suffix.casefold() in {".tex", ".sty", ".cls"}:
                queue.append(dependency)
        for directory, raw in re.findall(
            r"\\(?:import|subimport|inputfrom|subinputfrom)\s*"
            r"\{([^}]+)\}\s*\{([^}]+)\}",
            text,
            re.IGNORECASE,
        ):
            import_bases = [
                (base / directory.strip()).resolve()
                for base in bases
                if _inside((base / directory.strip()).resolve(), project_root)
            ]
            dependency = _resolve(raw, import_bases, project_root, (".tex", ""))
            if dependency:
                queue.append(dependency)
        local_sources = [
            *(
                (name, ".cls")
                for name in re.findall(
                    r"\\documentclass(?:\[[^]]*\])?\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
            ),
            *(
                (name, ".sty")
                for name in re.findall(
                    r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?"
                    r"\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
            ),
        ]
        for names, suffix in local_sources:
            for name in names.split(","):
                dependency = _resolve(name, bases, project_root, (suffix,))
                if dependency:
                    queue.append(dependency)
    return reachable


def _referenced_files(
    sources: set[Path],
    source_root: Path,
    project_root: Path,
) -> set[Path]:
    dependencies: set[Path] = set()
    graphic_dirs: list[Path] = []
    for source in sources:
        text = _tex_text(source)
        for block in re.findall(
            r"\\graphicspath\s*\{((?:\{[^}]*\}\s*)+)\}", text, re.IGNORECASE
        ):
            for raw in re.findall(r"\{([^}]*)\}", block):
                for base in _bases(source, source_root, project_root):
                    candidate = (base / raw.strip()).resolve()
                    if (
                        candidate.is_dir()
                        and _inside(candidate, project_root)
                        and candidate not in graphic_dirs
                    ):
                        graphic_dirs.append(candidate)

    for source in sources:
        text = _tex_text(source)
        bases = [*_bases(source, source_root, project_root), *graphic_dirs]
        references = [
            *(
                (raw, GRAPHIC_EXTENSIONS)
                for raw in re.findall(
                    r"\\includegraphics(?:\[[^]]*\])?\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
            ),
            *(
                (raw, (".bib",))
                for group in re.findall(
                    r"\\(?:bibliography|addbibresource)(?:\[[^]]*\])?"
                    r"\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
                for raw in group.split(",")
            ),
            *(
                (raw, (".bst",))
                for raw in re.findall(
                    r"\\bibliographystyle\s*\{([^}]+)\}", text, re.IGNORECASE
                )
            ),
            *(
                (raw, ("",))
                for raw in re.findall(
                    r"\\(?:lstinputlisting|verbatiminput|includepdf)"
                    r"(?:\[[^]]*\])?\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
            ),
            *(
                (raw, ("",))
                for raw in re.findall(
                    r"\\inputminted(?:\[[^]]*\])?\s*\{[^}]+\}\s*\{([^}]+)\}",
                    text,
                    re.IGNORECASE,
                )
            ),
        ]
        for raw, suffixes in references:
            dependency = _resolve(raw, bases, project_root, suffixes)
            if dependency:
                dependencies.add(dependency)
    return dependencies


def latex_source_bundle(source_root: str | Path) -> tuple[str, list[Path]]:
    """Return a stable digest and the files reachable from main.tex.

    Unused TeX drafts are excluded. Local includes, graphics, bibliography
    databases, classes, styles, and common external-file commands are included.
    """
    supplied = Path(source_root).expanduser().resolve()
    root = supplied.parent if supplied.is_file() else supplied
    entrypoint = supplied if supplied.is_file() else root / "main.tex"
    project_root = root.parent.resolve()
    sources = (
        _reachable_sources(entrypoint, root, project_root)
        if entrypoint.is_file()
        else set()
    )
    paths = sources | _referenced_files(sources, root, project_root)
    ordered = sorted(paths, key=lambda path: path.as_posix().casefold())
    digest = hashlib.sha256()
    digest.update(b"latex-reachable-bundle:v2\n")
    if not entrypoint.is_file():
        digest.update(b"<missing-main.tex>\n")
    for path in ordered:
        try:
            identity = path.relative_to(project_root).as_posix()
        except ValueError:
            identity = path.as_posix()
        digest.update(identity.encode("utf-8", errors="replace"))
        digest.update(b"::")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\n")
    return digest.hexdigest(), ordered
