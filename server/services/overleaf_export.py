"""Bounded paper-tree transfer for Overleaf repositories."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


GENERATED_FILES = {
    "main.pdf", "main.aux", "main.log", "main.out", "main.fls",
    "main.fdb_latexmk", "main.synctex.gz",
}
BLOCKED_FILES = {".env", ".env.local", "credentials.json", "secrets.json"}
BLOCKED_DIRECTORIES = {".git", ".merak", "__pycache__"}


def copy_research_tree(source: Path, destination: Path, *, prune: bool = True) -> None:
    """Copy a paper/figure tree without following links or exporting secrets."""
    if not source.is_dir():
        return
    source = source.resolve()
    destination_root = destination.resolve()
    copied: set[Path] = set()
    for current_dir, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(current_dir)
        dirnames[:] = [
            name for name in sorted(dirnames)
            if name not in BLOCKED_DIRECTORIES and not (current / name).is_symlink()
        ]
        relative = current.relative_to(source)
        target_dir = destination / relative
        if target_dir.is_symlink() or not target_dir.resolve().is_relative_to(destination_root):
            raise ValueError("Overleaf export destination escapes its repository")
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(filenames):
            source_file = current / name
            if name in GENERATED_FILES or name in BLOCKED_FILES or source_file.is_symlink():
                continue
            relative_file = relative / name
            target = destination / relative_file
            if target.is_symlink() or not target.resolve().is_relative_to(destination_root):
                raise ValueError("Overleaf export destination contains a linked file")
            copied.add(relative_file)
            shutil.copy2(source_file, target)
    if prune and destination.is_dir():
        _prune_export(destination, copied)


def _prune_export(destination: Path, copied: set[Path]) -> None:
    for current_dir, dirnames, filenames in os.walk(
        destination, topdown=False, followlinks=False,
    ):
        current = Path(current_dir)
        if ".git" in current.relative_to(destination).parts:
            continue
        for name in filenames:
            path = current / name
            relative = path.relative_to(destination)
            if (
                name not in GENERATED_FILES
                and name not in BLOCKED_FILES
                and ".git" not in relative.parts
                and relative not in copied
                and not path.is_symlink()
            ):
                path.unlink(missing_ok=True)
        for name in dirnames:
            path = current / name
            if name == ".git" or path.is_symlink():
                continue
            try:
                path.rmdir()
            except OSError:
                pass
