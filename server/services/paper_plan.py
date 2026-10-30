"""Canonical, evidence-bounded manuscript planning artifacts."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from .paper_plan_changes import bibliography_snapshot, inventory_hash, source_inventory
from .paper_plan_rendering import (
    asset_table,
    claims_table,
    evidence_gap_section,
    mechanism_section,
    section_plan,
)


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(path: Path, limit: int = 20000) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""


def _clean(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").replace("|", "/").split())[:limit]


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _plan_inputs(
    root: Path,
    research_direction: str,
    target_venue: str,
    assets: dict[str, Any],
    synthetic_valid: bool,
) -> dict[str, Any]:
    selected = _json(root / "ideas" / "SELECTED_IDEA.json")
    publication = selected.get("publication") if isinstance(selected.get("publication"), dict) else {}
    method = _json(root / "experiments" / "METHOD_CONTRACT.json")
    from .scientific_evidence import scientific_evidence_service
    from .paper_budget import paper_budget_service

    executed_valid, _, _ = scientific_evidence_service.validate_executed_metrics(root)
    evidence_mode = "synthetic_benchmark" if synthetic_valid else (
        "executed" if executed_valid else "pending"
    )
    budget = paper_budget_service.load(root)
    return {
        "selected": selected,
        "narrative": _text(root / "NARRATIVE_REPORT.md", 8000),
        "title": _clean((publication or {}).get("title") or research_direction or "Research manuscript"),
        "hypothesis": _clean(
            selected.get("hypothesis") or selected.get("problem_statement")
            or selected.get("title") or research_direction or "Research manuscript"
        ),
        "claims": [
            {**item, "statement": item.get("publication_statement")}
            for item in _records(selected.get("claims"))
        ],
        "mechanisms": [
            {**item, "name": item.get("publication_name"),
             "description": item.get("publication_description")}
            for item in _records(selected.get("mechanisms"))
        ],
        "claim_plans": {
            str(item.get("idea_claim_id") or item.get("claim_id") or ""): item
            for item in _records(method.get("claim_evidence_plan"))
        },
        "evidence_mode": evidence_mode,
        "section_pages": budget.section_pages if budget else {},
        "venue": target_venue or (budget.venue if budget else "unspecified venue"),
        "asset_records": _records(assets.get("assets")),
    }


class PaperPlanService:
    """Own the single canonical plan and its source/output hash bindings.

    Only ``paper/PAPER_PLAN.md`` is consumed. Unregistered root-level files
    cannot be promoted to accepted plans by copying or by changing timestamps.
    """

    canonical_relative_path = Path("paper") / "PAPER_PLAN.md"
    build_relative_path = Path(".merak") / "PAPER_PLAN_BUILD.json"

    @staticmethod
    def is_valid(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size < 700:
            return False
        content = _text(path, 200000).casefold()
        groups = (
            ("one-sentence contribution", "core contribution", "核心贡献", "一句话贡献"),
            ("claims-evidence", "claim-evidence", "claim", "论点", "证据矩阵"),
            ("section plan", "introduction", "method", "章节计划", "章节"),
            ("figure plan", "table plan", "figure", "图表计划", "图表"),
            ("evidence gap", "pending", "limitation", "证据缺口", "待验证", "局限"),
        )
        return sum(any(signal in content for signal in group) for group in groups) >= 4

    def path(self, project_path: str | Path) -> Path:
        return Path(project_path).expanduser().resolve() / self.canonical_relative_path

    def _source_paths(self, root: Path) -> list[Path]:
        return [
            root / "NARRATIVE_REPORT.md",
            root / "ideas" / "SELECTED_IDEA.json",
            root / "experiments" / "METHOD_CONTRACT.json",
            root / "experiments" / "EXPERIMENT_PLAN.md",
            root / "experiments" / "results" / "analysis.md",
            root / "literature" / "references.bib",
            root / "paper" / "PAPER_BUDGET.json",
            root / "paper" / "PAPER_PLAN.json",
            root / "experiments" / "RUN_SPEC.json",
            root / "experiments" / "configs" / "main.yaml",
            root / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json",
            root / "experiments" / "results" / "ANALYSIS_BUILD.json",
        ]

    @staticmethod
    def _source_hash(root: Path, paths: list[Path]) -> str:
        return inventory_hash(source_inventory(root, paths))

    def is_current(self, project_path: str | Path) -> bool:
        root = Path(project_path).expanduser().resolve()
        plan = root / self.canonical_relative_path
        if not self.is_valid(plan):
            return False
        from .paper_plan_evidence import verified_simulation_plan_evidence
        verified_simulation_plan_evidence(root)
        sources = self._source_paths(root)
        source_hash = self._source_hash(root, sources)
        build = _json(root / self.build_relative_path)
        output_hash = hashlib.sha256(plan.read_bytes()).hexdigest()
        return bool(build.get("schema") == 1 and (
            build.get("source_bundle_sha256") == source_hash
            and build.get("output_sha256") == output_hash
        ))

    def record_existing(
        self,
        project_path: str | Path,
        *,
        generator: str = "model-authored:paper-plan",
        expected_source_hash: str | None = None,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        plan = root / self.canonical_relative_path
        if not self.is_valid(plan):
            return {}
        sources = self._source_paths(root)
        inventory = source_inventory(root, sources)
        source_hash = inventory_hash(inventory)
        if expected_source_hash is not None and source_hash != expected_source_hash:
            raise RuntimeError("Paper-plan sources changed during authoring; fresh source review required")
        payload = {
            "schema": 1,
            "generated_at": time.time(),
            "generator": generator,
            "plan_path": self.canonical_relative_path.as_posix(),
            "source_bundle_sha256": source_hash,
            "source_fingerprints": inventory,
            "bibliography_snapshot": bibliography_snapshot(root, inventory),
            "sources": [
                path.relative_to(root).as_posix()
                for path in sources
                if path.is_file() and path.stat().st_size > 0
            ],
            "output_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        }
        build = root / self.build_relative_path
        atomic_write_json(build, payload)
        return payload

    def _current_plan_can_be_reused(
        self,
        root: Path,
        plan_path: Path,
        *,
        synthetic_valid: bool,
        force: bool,
    ) -> bool:
        if force or not self.is_current(root):
            return False
        current = _text(plan_path, 200000)
        if synthetic_valid:
            return "**Evidence mode:** synthetic_benchmark" in current
        if "**Evidence mode:** pending" not in current:
            return True
        from .scientific_evidence import scientific_evidence_service

        executed_valid, _, _ = scientific_evidence_service.validate_executed_metrics(root)
        return not executed_valid

    def ensure(
        self,
        project_path: str | Path,
        research_direction: str = "",
        *,
        target_venue: str = "",
        force: bool = False,
        generator: str = "deterministic:evidence-paper-plan",
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        plan_path = root / self.canonical_relative_path
        assets = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
        from .paper_plan_evidence import verified_simulation_plan_evidence
        synthetic_valid = verified_simulation_plan_evidence(root)
        if self._current_plan_can_be_reused(
            root, plan_path, synthetic_valid=synthetic_valid, force=force
        ):
            return {"generated": False, "path": str(plan_path), "valid": True}

        context = _plan_inputs(
            root, research_direction, target_venue, assets, synthetic_valid
        )
        selected = context["selected"]
        narrative = context["narrative"]
        title = context["title"]
        hypothesis = context["hypothesis"]
        claims = context["claims"]
        mechanisms = context["mechanisms"]
        claim_plans = context["claim_plans"]
        evidence_mode = context["evidence_mode"]
        section_pages = context["section_pages"]
        venue = context["venue"]
        asset_records = context["asset_records"]

        lines = [
            "# Paper Plan",
            "",
            f"**Working title:** {title}",
            f"**Target venue:** {_clean(venue)}",
            f"**Evidence mode:** {evidence_mode}",
            "",
            "## One-Sentence Contribution",
            "",
            hypothesis.rstrip(".") + ".",
            "",
        ]
        lines.extend(claims_table(claims, claim_plans, evidence_mode, _clean))
        lines.extend(("", *mechanism_section(mechanisms, _clean)))
        lines.extend(("", *section_plan(section_pages)))
        lines.extend(("", *asset_table(asset_records, evidence_mode, _clean)))
        lines.extend((
            "",
            *evidence_gap_section(
                selected,
                evidence_mode,
                bool(narrative),
                _clean,
            ),
        ))
        atomic_write_text(plan_path, "\n".join(lines).rstrip() + "\n")
        build = self.record_existing(root, generator=generator)
        return {
            "generated": True,
            "path": str(plan_path),
            "valid": self.is_valid(plan_path),
            "build_path": str(root / self.build_relative_path),
            "source_bundle_sha256": build.get("source_bundle_sha256", ""),
        }


paper_plan_service = PaperPlanService()
