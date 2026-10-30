"""Venue selection and bounded installation of LaTeX template assets."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .manuscript_text import read_text, sha256

ErrorFactory = Callable[[str, Iterable[str]], Exception]


def canonical_venue(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = (
        ("neurips", "neurips"), ("nips", "neurips"), ("iclr", "iclr"),
        ("icml", "icml"), ("cvpr", "cvpr"), ("acl", "acl"), ("aaai", "aaai"),
    )
    return next(
        (canonical for marker, canonical in aliases
         if normalized == marker or normalized.startswith(marker)),
        "",
    )


def canonical_venue_family(
    requested_venue: str, publication_style: dict[str, Any]
) -> str:
    venue = str(requested_venue or "").casefold()
    family = str(publication_style.get("family") or "")
    if any(token in venue for token in ("nature", "science", "cell", "pnas")):
        return "nature_science"
    if family in {"clinical_biomedical", "computational_biology"}:
        return "biomedical_journal"
    if family == "theoretical_formal":
        return "mathematics_theory"
    if family in {"social_behavioral", "qualitative_humanities"}:
        return "social_qualitative"
    systems = family in {"computer_systems", "engineering_systems"}
    venue_signal = "ieee" in venue or "acm" in venue or any(
        token in venue
        for token in ("eccv", "emnlp", "naacl", "sig", "usenix", "kdd",
                      "ijcai", "sosp", "osdi", "icse", "chi")
    )
    return "ieee_acm_journal" if systems or venue_signal else "generic_journal"


def template_source_fingerprint(
    source_path: str | Path, extensions: frozenset[str]
) -> str:
    source = Path(source_path).expanduser()
    if not source.exists():
        return ""
    if source.is_file():
        return sha256(source)
    digest, included = hashlib.sha256(), 0
    for path in sorted(
        (item for item in source.rglob("*")
         if item.is_file() and item.suffix.casefold() in extensions),
        key=lambda item: item.as_posix().casefold(),
    ):
        if included >= 800:
            break
        try:
            relative, payload = path.relative_to(source).as_posix(), path.read_bytes()
        except OSError:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"::")
        digest.update(payload)
        digest.update(b"\n")
        included += 1
    return digest.hexdigest() if included else ""


def template_roots(module_path: Path) -> tuple[Path, ...]:
    packaged_skills = os.environ.get("MERAK_SKILLS_PATH", "").strip()
    if packaged_skills:
        return (Path(packaged_skills).expanduser().resolve() / "paper-write" / "templates",)
    repository = module_path.resolve().parents[2]
    return (repository / "merak-skills" / "paper-write" / "templates",)


def install_venue_assets(
    paper_root: Path,
    venue_key: str,
    *,
    bundles: dict[str, dict[str, Any]],
    roots: Iterable[Path],
    error_factory: ErrorFactory,
) -> dict[str, Any]:
    bundle = bundles[venue_key]
    installed, missing = [], []
    roots = tuple(roots)
    for filename in bundle["assets"]:
        destination = paper_root / filename
        if destination.is_file() and destination.stat().st_size > 0:
            installed.append(filename)
            continue
        source = next(
            (root / filename for root in roots if (root / filename).is_file()), None
        )
        if source is None:
            missing.append(filename)
        else:
            shutil.copy2(source, destination)
            installed.append(filename)
    if missing:
        raise error_factory(
            "assembly",
            ["target venue template assets are unavailable: " + ", ".join(missing)],
        )
    return {
        "key": venue_key,
        "label": str(bundle["label"]),
        "mode": "anonymous_review",
        "official_assets_bundled": True,
        "assets": installed,
    }


def choose_custom_template_main(
    snapshot_root: Path, preferred: Optional[Path] = None
) -> Optional[Path]:
    if preferred is not None and preferred.is_file() and preferred.suffix.casefold() == ".tex":
        text = read_text(preferred)
        if "\\documentclass" in text and "\\begin{document}" in text:
            return preferred
    preferred_names = {"main.tex": 0, "manuscript.tex": 1,
                       "template.tex": 2, "sample.tex": 3}
    candidates: list[tuple[int, int, str, Path]] = []
    for path in snapshot_root.rglob("*.tex"):
        text = read_text(path)
        if "\\documentclass" not in text or "\\begin{document}" not in text:
            continue
        try:
            depth = len(path.relative_to(snapshot_root).parts)
        except ValueError:
            depth = 99
        candidates.append((preferred_names.get(path.name.casefold(), 10),
                           depth, path.as_posix().casefold(), path))
    return min(candidates)[-1] if candidates else None


def install_custom_venue_template(
    paper_root: Path,
    source_value: str,
    *,
    extensions: frozenset[str],
    dependency_extensions: frozenset[str],
    reserved_targets: frozenset[str],
    error_factory: ErrorFactory,
) -> tuple[dict[str, Any], str, str]:
    source = Path(source_value).expanduser().resolve()
    _validate_source(source, paper_root, error_factory)
    snapshot_root = paper_root / "venue_template"
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    preferred = _snapshot_source(
        source, snapshot_root, extensions, error_factory
    )
    main_template = choose_custom_template_main(snapshot_root, preferred)
    content_root = _content_root(snapshot_root, main_template, preferred)
    class_source, style_source = _class_and_style_sources(
        content_root, preferred
    )
    installed = _install_dependencies(
        paper_root, content_root, main_template,
        dependency_extensions, reserved_targets,
    )
    template_text = read_text(main_template) if main_template else ""
    documentclass = _fallback_documentclass(
        template_text, class_source, style_source, error_factory
    )
    metadata = {
        "key": "custom",
        "label": f"User-supplied venue template: {source.name}",
        "mode": "user_supplied_template",
        "official_assets_bundled": False,
        "user_supplied": True,
        "source_path": str(source),
        "source_sha256": template_source_fingerprint(source, extensions),
        "main_template": main_template.relative_to(snapshot_root).as_posix()
        if main_template is not None else "",
        "assets": installed,
        "snapshot_directory": "venue_template",
    }
    return metadata, template_text, documentclass


def _validate_source(
    source: Path, paper_root: Path, error_factory: ErrorFactory
) -> None:
    if not source.exists():
        raise error_factory(
            "assembly", [f"user-supplied venue template does not exist: {source}"]
        )
    if source.is_file() and source.suffix.casefold() not in {".tex", ".cls", ".sty", ".zip"}:
        raise error_factory(
            "assembly",
            ["venue template must be a TeX file, class/style file, directory, or ZIP archive"],
        )
    source_root = source if source.is_dir() else source.parent
    if source.suffix.casefold() != ".zip" and paper_root.resolve().is_relative_to(source_root.resolve()):
        raise error_factory(
            "assembly",
            ["select the template directory itself, not the research project or one of its ancestors"],
        )


def _snapshot_source(
    source: Path,
    snapshot_root: Path,
    extensions: frozenset[str],
    error_factory: ErrorFactory,
) -> Optional[Path]:
    if source.is_file() and source.suffix.casefold() == ".zip":
        _extract_archive(source, snapshot_root, extensions, error_factory)
        return None
    source_root = source if source.is_dir() else source.parent
    preferred: Optional[Path] = None
    copied, total_bytes = 0, 0
    for path in _template_files(source_root, extensions):
        try:
            resolved, size = path.resolve(), path.stat().st_size
            if not resolved.is_relative_to(source_root.resolve()):
                continue
        except OSError:
            continue
        copied, total_bytes = _check_budget(
            copied + 1, total_bytes + size, error_factory
        )
        destination = snapshot_root / path.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if source.is_file() and resolved == source:
            preferred = destination
    return preferred


def _extract_archive(
    source: Path, snapshot_root: Path, extensions: frozenset[str],
    error_factory: ErrorFactory,
) -> None:
    copied, total_bytes = 0, 0
    try:
        with zipfile.ZipFile(source) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                relative = Path(info.filename.replace("\\", "/"))
                if (info.is_dir() or relative.is_absolute() or ".." in relative.parts
                        or relative.suffix.casefold() not in extensions):
                    continue
                copied, total_bytes = _check_budget(
                    copied + 1, total_bytes + info.file_size, error_factory
                )
                destination = (snapshot_root / relative).resolve()
                if not destination.is_relative_to(snapshot_root.resolve()):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source_handle, destination.open("wb") as target:
                    shutil.copyfileobj(source_handle, target)
    except (OSError, zipfile.BadZipFile) as exc:
        raise error_factory(
            "assembly", [f"cannot read venue template archive: {exc}"]
        ) from exc


def _check_budget(
    copied: int, total_bytes: int, error_factory: ErrorFactory
) -> tuple[int, int]:
    if copied > 800 or total_bytes > 150 * 1024 * 1024:
        raise error_factory(
            "assembly", ["venue template exceeds the 800-file or 150 MB safety limit"]
        )
    return copied, total_bytes


def _template_files(root: Path, extensions: frozenset[str]) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*")
         if path.is_file() and path.suffix.casefold() in extensions),
        key=lambda path: path.as_posix().casefold(),
    )


def _content_root(
    snapshot: Path, main: Optional[Path], preferred: Optional[Path]
) -> Path:
    return main.parent if main is not None else preferred.parent if preferred is not None else snapshot


def _class_and_style_sources(
    content_root: Path, preferred: Optional[Path]
) -> tuple[Optional[Path], Optional[Path]]:
    class_source = (
        preferred if preferred is not None and preferred.suffix.casefold() == ".cls"
        else next(iter(sorted(content_root.glob("*.cls"))), None)
    )
    style_source = (
        preferred if preferred is not None and preferred.suffix.casefold() == ".sty"
        else None
    )
    return class_source, style_source


def _install_dependencies(
    paper_root: Path,
    content_root: Path,
    main_template: Optional[Path],
    extensions: frozenset[str],
    reserved: frozenset[str],
) -> list[str]:
    installed = []
    for path in _template_files(content_root, extensions):
        if main_template is not None and path.resolve() == main_template.resolve():
            continue
        relative = path.relative_to(content_root)
        if not relative.parts or relative.parts[0].casefold() in reserved:
            continue
        destination = (paper_root / relative).resolve()
        if not destination.is_relative_to(paper_root.resolve()):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        installed.append(relative.as_posix())
    return installed


def _fallback_documentclass(
    template_text: str,
    class_source: Optional[Path],
    style_source: Optional[Path],
    error_factory: ErrorFactory,
) -> str:
    if template_text:
        return ""
    if class_source is not None:
        return f"\\documentclass{{{class_source.stem}}}"
    if style_source is not None:
        return "\\documentclass[11pt]{article}\n" + f"\\usepackage{{{style_source.stem}}}"
    raise error_factory(
        "assembly", ["venue template contains neither a document shell nor a LaTeX class"]
    )
