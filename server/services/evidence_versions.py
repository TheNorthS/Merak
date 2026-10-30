"""Explicit, review-bound evidence replacement; old bytes remain archived on failure or success."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from ..utils.atomic_write import atomic_write_json, atomic_write_bytes, path_lock
from .planning_input_identity import planning_identity, PLANNING_SOURCES

MANIFEST = "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def version_plan(root: Path, direction: str, options: dict) -> dict:
    from .evidence_publication_recovery import pending_publication
    pending = pending_publication(root)
    identity = planning_identity(root, direction, **{key: str(options.get(key) or "") for key in
                                ("target_venue", "research_family", "study_archetype")},
                                 evidence_mode=str(options.get("non_experiment_evidence_mode") or "design_only"))
    original = root / ".merak/PLANNING_INPUTS.json"
    prior = json.loads(original.read_text(encoding="utf-8")) if original.is_file() else {}
    changed = [p for p, digest in identity["sources"].items() if prior.get("sources", {}).get(p) != digest]
    manifest_hash = pending.get("previous", {}).get(MANIFEST, _sha(root / MANIFEST))
    return {"input_sha256": identity["sha256"], "manifest_sha256": manifest_hash,
            "interrupted_publication": bool(pending),
            "changed_sources": changed, "prior_identity_known": bool(prior), "mode": identity["settings"]["evidence_mode"]}


class EvidenceVersionRequired(ValueError):
    def __init__(self, root: Path, input_hash: str):
        super().__init__("EVIDENCE_VERSION_REQUIRED: Existing simulation evidence does not match the current planning inputs; "
                         "no automatic migration or regeneration. Review changed sources and explicitly create a new evidence version.")
        self.input_hash = input_hash
        self.manifest_hash = _sha(root / MANIFEST)


def _copy_inputs(root: Path, stage: Path) -> dict[str, str]:
    files = {root / path for path in PLANNING_SOURCES}
    files.update(root / path for path in ("paper/PUBLICATION_STYLE.json", "literature/references.bib",
                 "literature/survey.md", "experiments/IMPLEMENTATION_BLUEPRINT.json", ".merak/research_strategy.json"))
    files.update((root / "experiments/src").rglob("*.py"))
    copied = {}
    for path in sorted(files):
        if not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Evidence source escapes project")
        relative = path.relative_to(root).as_posix()
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied[relative] = _sha(path)
    return copied


def _publish(root: Path, stage: Path, archive: Path, copied: dict, validate: Callable) -> None:
    changes = {p.relative_to(stage).as_posix(): p for p in stage.rglob("*")
               if p.is_file() and _sha(p) != copied.get(p.relative_to(stage).as_posix())}
    if MANIFEST not in changes:
        raise ValueError("Evidence producer did not create its manifest")
    for relative in copied:
        if relative in changes and relative != "paper/PUBLICATION_STYLE.json":
            raise ValueError(f"Evidence producer modified a frozen scientific input: {relative}")
    for relative, source in changes.items():
        if source.is_symlink() or not source.resolve().is_relative_to(stage.resolve()):
            raise ValueError("Evidence candidate contains an unsafe link")
        if not relative.startswith(("experiments/results/", "figures/", "paper/", ".merak/")):
            raise ValueError(f"Evidence output is outside producer ownership: {relative}")
    backup = archive / "previous"
    _archive_owned_evidence(root, backup)
    previous = {}
    for relative in changes:
        target = root / relative
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ValueError("Evidence output escapes project")
        previous[relative] = _sha(target)
        if target.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    receipt = {"schema": 1, "status": "publishing", "previous": previous,
               "next": {p: _sha(path) for p, path in changes.items()}}
    atomic_write_json(archive / "VERSION.json", receipt)
    try:
        for relative, source in changes.items():
            atomic_write_bytes(root / relative, source.read_bytes())
        validate(root)
    except BaseException:
        for relative, digest in previous.items():
            if digest:
                atomic_write_bytes(root / relative, (backup / relative).read_bytes())
            else:
                (root / relative).unlink(missing_ok=True)
        atomic_write_json(archive / "VERSION.json", {**receipt, "status": "rolled_back"})
        raise
    atomic_write_json(archive / "VERSION.json", {**receipt, "status": "published"})


def _archive_owned_evidence(root: Path, backup: Path) -> None:
    """Retain the full previous bundle, including files unchanged by the new producer."""
    prefixes = ("experiments/results/templates", "experiments/results/simulated", "figures/simulated", "figures/previews")
    files = [p for relative in prefixes for p in (root / relative).rglob("*") if p.is_file()]
    files += [root / p for p in (MANIFEST, "paper/PUBLICATION_STYLE.json", "paper/tables/synthetic_preview_results.tex",
              "paper/synthetic_preview_figures.tex", "paper/tables/planned_result_templates.tex", "figures/FIGURE_MANIFEST.json", ".merak/PLANNING_INPUTS.json")]
    for source in files:
        if not source.is_file():
            continue
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError("Previous evidence contains an unsafe link")
        target = backup / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


async def create_evidence_version(root: Path, direction: str, options: dict, approval: dict,
                                  *, producer: Callable, validate: Callable) -> dict:
    """A run lease belongs to the caller; the source and old manifest identities are checked twice."""
    root = root.resolve()
    from .evidence_publication_recovery import recover_publications
    plan = version_plan(root, direction, options)
    expected = {key: plan[key] for key in ("input_sha256", "manifest_sha256")}
    if approval != expected or not plan["manifest_sha256"] or plan["mode"] != "synthetic_preview":
        raise ValueError("EVIDENCE_VERSION_REQUIRED: Evidence version approval is absent, stale, or does not name existing synthetic evidence")
    with path_lock(root / MANIFEST):
        recover_publications(root)
        fresh = version_plan(root, direction, options)
        if any(fresh[key] != value for key, value in expected.items()):
            raise ValueError("EVIDENCE_VERSION_REQUIRED: Evidence version approval became stale during recovery")
    versions = root / ".merak/evidence-versions"
    for receipt in versions.glob("*/VERSION.json"):
        if json.loads(receipt.read_text(encoding="utf-8")).get("status") == "publishing":
            raise ValueError("Unfinished evidence publication requires rollback before a new version")
    archive = versions / uuid.uuid4().hex
    stage = archive / "candidate"
    stage.mkdir(parents=True)
    copied = _copy_inputs(root, stage)
    result = await producer(stage)
    validate(stage)
    with path_lock(root / MANIFEST):
        fresh = version_plan(root, direction, options)
        if any(fresh[key] != value for key, value in expected.items()):
            raise ValueError("EVIDENCE_VERSION_REQUIRED: Planning inputs changed while evidence was generated; candidate retained, canonical evidence untouched")
        _publish(root, stage, archive, copied, validate)
    return {**result, "version_id": archive.name, "archive": str(archive), "manifest_path": str(root / MANIFEST)}
