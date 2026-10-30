"""Coordinate the current draft-state and scientific-freeze services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from . import paper_draft_state


class PaperDraftStateMixin:
    """Expose stable service methods while implementations remain functional."""

    @staticmethod
    def directed_issue_signature(issues: Iterable[str]) -> str:
        return paper_draft_state.directed_issue_signature(issues)

    @staticmethod
    def _record_directed_attempt(
        paths: dict[str, Path], stage_id: str, issue_signature: str,
        attempts: int, artifact_signature: str = "",
    ) -> None:
        paper_draft_state.record_directed_attempt(
            paths, stage_id, issue_signature, attempts, artifact_signature
        )

    def paths(self, project_path: str | Path) -> dict[str, Path]:
        return paper_draft_state.drafting_paths(project_path)

    @staticmethod
    def source_paths(root: Path) -> list[Path]:
        return paper_draft_state.source_paths(root)

    @classmethod
    def authoring_source_paths(cls, root: Path) -> list[Path]:
        return paper_draft_state.authoring_source_paths(root)

    @staticmethod
    def signature_options(options: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return paper_draft_state.signature_options(options)

    @classmethod
    def gate_signature_options(
        cls, options: Optional[dict[str, Any]],
        stored_options: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        return paper_draft_state.gate_signature_options(options, stored_options)

    def authoring_input_hashes(self, project_path: str | Path) -> dict[str, str]:
        return paper_draft_state.authoring_input_hashes(self.paths(project_path)["root"])

    def scientific_freeze_inputs(self, project_path: str | Path) -> dict[str, str]:
        from .paper_scientific_freeze import scientific_freeze_inputs

        return scientific_freeze_inputs(self.paths(project_path)["root"])


    def rebind_layout_only_derived_inputs(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None, *,
        before_manifest: Optional[dict[str, Any]] = None,
        target_files: Optional[Iterable[str]] = None,
    ) -> dict[str, Any]:
        from .paper_scientific_freeze import rebind_layout_only_derived_inputs

        return rebind_layout_only_derived_inputs(
            self.paths(project_path)["root"], options,
            before_manifest=before_manifest, target_files=target_files,
        )

    @staticmethod
    def _refresh_simulation_table_binding(root: Path) -> list[str]:
        from .paper_scientific_freeze import refresh_simulation_table_binding

        return refresh_simulation_table_binding(root)

    def freeze_scientific_inputs(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_scientific_freeze import freeze_scientific_inputs

        return freeze_scientific_inputs(
            self.paths(project_path)["root"], options,
        )

    def validate_scientific_freeze(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from .paper_scientific_freeze import validate_scientific_freeze

        return validate_scientific_freeze(self.paths(project_path)["root"], options)

    def source_signature(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> str:
        from .paper_scientific_freeze import source_signature

        return source_signature(self.paths(project_path)["root"], options)

    def authoring_signature(
        self, project_path: str | Path,
        options: Optional[dict[str, Any]] = None,
    ) -> str:
        from .paper_scientific_freeze import authoring_signature

        return authoring_signature(self.paths(project_path)["root"], options)

    @staticmethod
    def evidence(root: Path) -> dict[str, Any]:
        return paper_draft_state.evidence_status(root)

    @staticmethod
    def analyse_tex_source(path: Path) -> dict[str, Any]:
        return paper_draft_state.analyse_tex_source(path)
