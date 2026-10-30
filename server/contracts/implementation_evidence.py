"""Typed model-to-runtime evidence patches for staged implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


SELECTOR_FIELDS = ("symbols", "data_keys", "anchors", "config_keys")


@dataclass(frozen=True)
class EvidenceReference:
    path: str
    selectors: dict[str, tuple[str, ...]]

    @classmethod
    def parse(cls, value: Any) -> "EvidenceReference":
        if not isinstance(value, dict):
            raise ValueError("evidence reference must be an object")
        if not isinstance(value.get("path"), str):
            raise ValueError("evidence path must be a project-relative string")
        path_value = value["path"].strip().replace("\\", "/")
        path = PurePosixPath(path_value)
        if (not path_value or path.is_absolute() or PureWindowsPath(path_value).drive
                or ".." in path.parts or ":" in path_value):
            raise ValueError("evidence path must be project-relative")
        selectors = {}
        for field in SELECTOR_FIELDS:
            items = value.get(field, [])
            if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(f"evidence {path_value}: {field} must be a list of non-empty strings")
            selectors[field] = tuple(item.strip() for item in items)
        selectors = {key: items for key, items in selectors.items() if items}
        if not selectors:
            raise ValueError("evidence reference requires a typed selector")
        if "config_keys" in selectors and path.suffix.lower() not in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
            raise ValueError(f"evidence {path_value}: config_keys require a structured configuration file; use symbols, data_keys or anchors for source code")
        return cls(path=path.as_posix(), selectors=selectors)

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, **{key: list(value) for key, value in self.selectors.items()}}


@dataclass(frozen=True)
class ImplementationEvidencePatch:
    check_id: str
    description: str
    evidence: tuple[EvidenceReference, ...]
    idea_mechanism_ids: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: Any) -> "ImplementationEvidencePatch":
        if not isinstance(value, dict):
            raise ValueError("implementation evidence patch must be an object")
        check_id = str(value.get("check_id") or value.get("id") or "").strip()
        description = str(value.get("description") or "").strip()
        if not check_id or not description:
            raise ValueError("implementation evidence patch requires check_id and description")
        evidence = tuple(EvidenceReference.parse(item) for item in value.get("evidence") or [])
        if not evidence:
            raise ValueError("implementation evidence patch requires evidence")
        mechanism_ids = value.get("idea_mechanism_ids", [])
        if not isinstance(mechanism_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in mechanism_ids
        ):
            raise ValueError("idea_mechanism_ids must be a list of non-empty stable IDs")
        if len(mechanism_ids) != len(set(item.strip() for item in mechanism_ids)):
            raise ValueError("idea_mechanism_ids contains duplicate mechanism IDs")
        return cls(
            check_id=check_id, description=description, evidence=evidence,
            idea_mechanism_ids=tuple(item.strip() for item in mechanism_ids),
        )

    def as_check(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "description": self.description,
            "evidence": [item.as_dict() for item in self.evidence],
        }


def parse_evidence_patch_document(value: Any) -> list[ImplementationEvidencePatch]:
    """Parse the one current integration patch document schema."""
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("implementation evidence patch document must use schema=1")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("implementation evidence patch document requires checks")
    patches = [ImplementationEvidencePatch.parse(item) for item in checks]
    ids = [item.check_id for item in patches]
    if len(ids) != len(set(ids)):
        raise ValueError("implementation evidence patch contains duplicate check IDs")
    return patches


@dataclass(frozen=True)
class IntegrationVerdict:
    passed: bool
    report_sha256: str
    issues: tuple[str, ...]

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "IntegrationVerdict":
        digest = str(report.get("output_sha256") or "").strip()
        if not digest:
            raise ValueError("integration verdict requires a deterministic output hash")
        return cls(
            passed=bool(report.get("passed")),
            report_sha256=digest,
            issues=tuple(str(item) for item in report.get("issues") or []),
        )
