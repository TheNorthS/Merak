"""Evidence-bounded narrative fallback derived from frozen research contracts."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from .narrative_rendering import narrative_context, render_narrative


_VOLATILE_SOURCE_METADATA_KEYS = frozenset({
    "created_at",
    "generated_at",
    "modified_at",
    "recorded_at",
    "rendered_at",
    "timestamp",
    "updated_at",
})


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(path: Path, limit: int = 12000) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]


def _semantic_source_bytes(path: Path) -> bytes:
    """Return stable source bytes without JSON builder timestamps."""
    if not path.is_file():
        return b"<missing>"
    raw = path.read_bytes()
    if path.suffix.casefold() != ".json":
        return raw
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        return raw
    if path.name == "SIMULATION_MANIFEST.json":
        from .paper_artifacts import simulation_manifest_semantic_payload
        return json.dumps(simulation_manifest_semantic_payload(payload), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    if path.name == "PLANNED_RESULT_MANIFEST.json":
        from .paper_artifacts import simulation_manifest_semantic_payload
        return json.dumps(simulation_manifest_semantic_payload(payload), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")

    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): stable(item)
                for key, item in sorted(
                    value.items(),
                    key=lambda pair: str(pair[0]),
                )
                if str(key).casefold() not in _VOLATILE_SOURCE_METADATA_KEYS
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    return json.dumps(
        stable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ScientificNarrativeService:
    narrative_relative_path = Path("NARRATIVE_REPORT.md")
    build_relative_path = Path(".merak") / "NARRATIVE_BUILD.json"

    @staticmethod
    def _source_hash(root: Path, paths: list[Path]) -> str:
        from .narrative_source_bindings import narrative_implementation_sha256
        digest = hashlib.sha256()
        digest.update(narrative_implementation_sha256().encode())
        for path in paths:
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"::")
            digest.update(_semantic_source_bytes(path))
            digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _source_paths(root: Path) -> list[Path]:
        """Return every semantic input that can change narrative conclusions."""
        from .narrative_source_bindings import narrative_scientific_sources
        return narrative_scientific_sources(root, [
            root / "ideas" / "SELECTED_IDEA.json",
            root / "experiments" / "METHOD_CONTRACT.json",
            root / "experiments" / "results" / "analysis.md",
            root / "experiments" / "results" / "templates"
            / "PLANNED_RESULT_MANIFEST.json",
            root / "literature" / "survey.md",
            root / "experiments" / "results" / "simulated"
            / "SIMULATION_MANIFEST.json",
            root / "experiments" / "results" / "simulated"
            / "claim_evidence.csv",
            root / "experiments" / "results" / "simulated"
            / "paired_comparisons.csv",
        ])

    def record_existing(
        self,
        project_path: str | Path,
        *,
        generator: str = "model-authored:narrative-node",
    ) -> dict[str, Any]:
        """Bind a just-authored narrative to the current upstream evidence."""
        root = Path(project_path).expanduser().resolve()
        narrative_path = root / self.narrative_relative_path
        if not narrative_path.is_file() or narrative_path.stat().st_size == 0:
            return {}
        source_paths = self._source_paths(root)
        planned_manifest_path = (
            root / "experiments" / "results" / "templates"
            / "PLANNED_RESULT_MANIFEST.json"
        )
        build = {
            "schema": 1,
            "generated_at": time.time(),
            "generator": generator,
            "evidence_mode": str(
                _json(planned_manifest_path).get("evidence_mode") or "planned"
            ),
            "source_bundle_sha256": self._source_hash(root, source_paths),
            "sources": [path.relative_to(root).as_posix() for path in source_paths],
            "output_path": self.narrative_relative_path.as_posix(),
            "output_sha256": hashlib.sha256(narrative_path.read_bytes()).hexdigest(),
        }
        atomic_write_json(root / self.build_relative_path, build)
        return build

    def _reuse_existing(
        self,
        root: Path,
        narrative_path: Path,
        build_path: Path,
        source_paths: list[Path],
        *,
        force: bool,
        preserve_researcher_authored: bool,
    ) -> dict[str, Any] | None:
        if not narrative_path.is_file() or narrative_path.stat().st_size <= 0:
            return None
        build = _json(build_path)
        generator = str(build.get("generator") or "")
        managed = generator.startswith((
            "deterministic:", "model-authored:", "researcher-authored:",
        ))
        researcher_authored = generator.startswith("researcher-authored:")
        source_hash = self._source_hash(root, source_paths)
        output_hash = hashlib.sha256(narrative_path.read_bytes()).hexdigest()
        recorded_output = str(build.get("output_sha256") or "")
        if not force and managed and (
            build.get("source_bundle_sha256") == source_hash
            and recorded_output == output_hash
        ):
            return {"generated": False, "path": str(narrative_path), "build_path": str(build_path)}
        authored = generator.startswith(("model-authored:", "researcher-authored:"))
        if not force and authored and recorded_output == output_hash:
            # Stale provenance must reach the author's gate, not erase authored
            # interpretation or silently bind it to sources it has not reviewed.
            return {
                "generated": False, "path": str(narrative_path),
                "build_path": str(build_path), "source_drift": True,
                "provenance_recorded": True,
            }
        if force or not preserve_researcher_authored or (managed and not researcher_authored):
            return None
        manifest = root / "experiments" / "results" / "templates" / "PLANNED_RESULT_MANIFEST.json"
        atomic_write_json(build_path, {
            "schema": 1, "generated_at": time.time(),
            "generator": "researcher-authored:source-bound",
            "evidence_mode": str(_json(manifest).get("evidence_mode") or "planned"),
            "source_bundle_sha256": source_hash,
            "sources": [path.relative_to(root).as_posix() for path in source_paths],
            "output_path": self.narrative_relative_path.as_posix(),
            "output_sha256": output_hash,
        })
        return {
            "generated": False, "path": str(narrative_path),
            "build_path": str(build_path), "provenance_recorded": True,
        }

    def ensure(
        self,
        project_path: str | Path,
        research_direction: str = "",
        *,
        force: bool = False,
        preserve_researcher_authored: bool = True,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        narrative_path = root / self.narrative_relative_path
        build_path = root / self.build_relative_path
        source_paths = self._source_paths(root)
        existing = self._reuse_existing(
            root,
            narrative_path,
            build_path,
            source_paths,
            force=force,
            preserve_researcher_authored=preserve_researcher_authored,
        )
        if existing is not None:
            return existing
        context = narrative_context(root, research_direction)
        evidence_mode = str(context["evidence_mode"])
        atomic_write_text(narrative_path, render_narrative(context))
        build = {
            "schema": 1,
            "generated_at": time.time(),
            "generator": "deterministic:evidence-bounded-narrative",
            "evidence_mode": evidence_mode,
            "source_bundle_sha256": self._source_hash(root, source_paths),
            "sources": [path.relative_to(root).as_posix() for path in source_paths],
            "output_path": self.narrative_relative_path.as_posix(),
            "output_sha256": hashlib.sha256(narrative_path.read_bytes()).hexdigest(),
        }
        atomic_write_json(build_path, build)
        return {
            "generated": True,
            "path": str(narrative_path),
            "build_path": str(build_path),
            "evidence_mode": evidence_mode,
        }


scientific_narrative_service = ScientificNarrativeService()
