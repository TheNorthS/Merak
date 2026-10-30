"""Recover canonical figure files when a candidate fails before commit."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class FigureFileTransaction:
    """Snapshot only one semantic stem and the manifest inside its project."""

    def __init__(self, project_root: Path, output_dir: Path, semantic_key: str) -> None:
        self.root = project_root.resolve()
        self.output_dir = output_dir.resolve()
        self.semantic_key = semantic_key
        transactions = self.root / ".merak/transactions"
        transactions.mkdir(parents=True, exist_ok=True)
        self._temporary = transactions / f"figure-{semantic_key}-{uuid.uuid4().hex[:12]}"
        self._temporary.mkdir()
        self._before: dict[Path, Path] = {}
        self._initial_paths: set[Path] = set()
        self._capture()

    def _owned_paths(self) -> list[Path]:
        candidates = list(self.output_dir.glob(f"{self.semantic_key}.*"))
        candidates.append(self.root / "figures/FIGURE_MANIFEST.json")
        return [
            path.resolve() for path in candidates
            if path.is_file() and path.resolve().is_relative_to(self.root)
        ]

    def _capture(self) -> None:
        for source in self._owned_paths():
            relative = source.relative_to(self.root)
            backup = self._temporary / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            self._before[source] = backup
            self._initial_paths.add(source)

    def rollback(self) -> None:
        for candidate in self._owned_paths():
            if candidate not in self._initial_paths:
                candidate.unlink(missing_ok=True)
        for target, backup in self._before.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        self.close()

    def close(self) -> None:
        shutil.rmtree(self._temporary, ignore_errors=True)
        parent = self._temporary.parent
        try:
            parent.rmdir()
        except OSError:
            pass
