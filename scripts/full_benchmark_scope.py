"""Isolated full-benchmark writes and immutable original/numerical boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sys
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch


FROZEN_DIRECTORIES = ("experiments/src", "experiments/configs", "experiments/results/simulated",
                      "experiments/results/templates", "figures/simulated", ".merak/source-evidence")
FROZEN_FILES = ("experiments/EXPERIMENT_PLAN.md", "experiments/RUN_SPEC.json")
FROZEN_WORKFLOW_INPUTS = ("ideas/SELECTED_IDEA.json", *FROZEN_FILES,
    "experiments/configs", "experiments/src", "experiments/results/simulated",
    "experiments/results/templates", "figures/simulated")
OWNED_ROOT_FILES = frozenset({"MANIFEST.md", "NARRATIVE_REPORT.md", "FULL_BENCHMARK_REPORT.json"})
MODEL_OWNER: ContextVar[str] = ContextVar("full_benchmark_model_owner", default="")
_TABLE_PRODUCER: ContextVar[Path | None] = ContextVar("full_benchmark_table_producer", default=None)
_TABLE_STAGE: ContextVar[Path | None] = ContextVar("full_benchmark_table_stage", default=None)
SEMANTIC_MANIFESTS = ("experiments/results/simulated/SIMULATION_MANIFEST.json",
                      "experiments/results/templates/PLANNED_RESULT_MANIFEST.json")
TEN_NODES = ("exp-design", "exp-run", "results", "narrative", "figure", "paper", "review", "audit", "compile", "ppt")
PIPELINE_NODES = ("lit", "idea", "novelty", *TEN_NODES)
METHOD_SCENE_GUIDANCE = (
    "Read the current experiments/METHOD_CONTRACT.json before editing. Use a local Edit of scientific_scene; "
    "do not reconstruct the whole contract from a schema example. Keep every existing claim, outcome, failure "
    "condition, evaluation, comparator, mechanism design requirement, data field, identifier and all other "
    "frozen scientific values EXACTLY unchanged. Preserve current verified implementation_checks and code "
    "evidence; do not replace them with empty or staged-pending evidence. The existing implementation metadata "
    "is not scientific execution, so do not downgrade it just to follow a generic new-design status example. "
    "Only exp-design may edit the method; runtime source bindings and all genuine acceptance gates still apply."
)


class MethodScopeViolation(PermissionError):
    """A rejected model proposal, recoverable only through a different valid edit."""


def _csv_target(path: Path) -> bool:
    return path.suffix.casefold() == ".csv" or re.fullmatch(
        r"\..+\.csv\.\d+\.\d+\.[a-f0-9]{32}\.tmp", path.name, re.IGNORECASE,
    ) is not None


def _owned_root_file(path: Path, root: Path) -> bool:
    if path.parent != root:
        return False
    temporary = re.fullmatch(r"\.(.+)\.\d+\.\d+\.[a-f0-9]{32}\.tmp", path.name)
    return (temporary[1] if temporary else path.name) in OWNED_ROOT_FILES


def _owned_table_stage(root: Path, path: Path) -> bool:
    stage = _TABLE_STAGE.get()
    return bool(not MODEL_OWNER.get() and _TABLE_PRODUCER.get() == root and stage is not None
                and stage.parent == root / ".merak/transactions" and stage.name.startswith("publication-tables-")
                and path.is_relative_to(stage) and path != stage)


@contextmanager
def trusted_publication_table_staging(root: Path):
    """Grant CSV staging only inside the trusted synchronous table producer.

    The real tempfile allocator identifies its exact fresh transaction path.
    Model tools never receive the token; canonical numerical files stay frozen.
    Module-local patching leaves unrelated tempfile users and threads unchanged.
    """
    from server.services import paper_submission_tables as producer
    from server.services import simulation_table_publication_refresh as refresh_producer

    root = root.resolve(strict=True)
    original, temporary_directory = producer.write_submission_tables, producer.tempfile.TemporaryDirectory
    original_refresh = refresh_producer.refresh_simulation_publication_tables

    @contextmanager
    def staged_directory(*args, **kwargs):
        if (MODEL_OWNER.get() or _TABLE_PRODUCER.get() != root or args
                or kwargs.get("prefix") != "publication-tables-"
                or Path(kwargs.get("dir", "")).resolve() != root / ".merak/transactions"
                or set(kwargs) != {"prefix", "dir"}):
            raise PermissionError("Table staging requires its trusted producer and exact transaction allocator")
        transaction = temporary_directory(**kwargs)
        stage = Path(transaction.name).resolve(strict=True)
        if stage.parent != root / ".merak/transactions" or stage.is_symlink():
            raise PermissionError("Publication table stage escapes its owned transaction directory")
        token = _TABLE_STAGE.set(stage)
        try:
            with transaction as directory:
                yield directory
        finally:
            _TABLE_STAGE.reset(token)

    def write_tables(evidence):
        if MODEL_OWNER.get() or Path(evidence.root).resolve() != root:
            raise PermissionError("Model tools or foreign projects cannot invoke trusted table staging")
        token = _TABLE_PRODUCER.set(root)
        try:
            return original(evidence)
        finally:
            _TABLE_PRODUCER.reset(token)

    def refresh_tables(project):
        if MODEL_OWNER.get() or Path(project).resolve() != root:
            raise PermissionError("Model tools or foreign projects cannot invoke trusted table staging")
        token = _TABLE_PRODUCER.set(root)
        try:
            return original_refresh(project)
        finally:
            _TABLE_PRODUCER.reset(token)

    with patch.object(producer, "tempfile", SimpleNamespace(TemporaryDirectory=staged_directory)), \
            patch.object(producer, "write_submission_tables", write_tables), \
            patch.object(refresh_producer, "tempfile", SimpleNamespace(TemporaryDirectory=staged_directory)), \
            patch.object(refresh_producer, "refresh_simulation_publication_tables", refresh_tables):
        yield


def tree_hashes(root: Path) -> dict[str, str]:
    """Hash every regular source file; linked originals are never copied or edited."""
    root = root.resolve(strict=True)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Benchmark source contains a linked path outside its ownership")
        if path.is_file():
            if path.stat().st_nlink > 1:
                raise ValueError("Benchmark source contains a hard-linked file")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def numerical_fingerprint(root: Path) -> dict[str, Any]:
    """Bind all CSVs and both semantic manifests, not a hand-picked subset."""
    from server.services.paper_artifacts import semantic_derived_hash

    hashes = tree_hashes(root)
    semantic = {}
    for relative in SEMANTIC_MANIFESTS:
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        semantic[relative] = semantic_derived_hash(relative, payload)
    return {"csv": {name: digest for name, digest in hashes.items() if name.casefold().endswith(".csv")},
            "semantic_manifests": semantic}


def write_is_allowed(root: Path, value: Any, *, rerun_literature: bool, rerun_source_owners: bool = False) -> bool:
    from scripts.verify_offline_suite import canonical_io_path

    if not isinstance(value, (str, bytes, os.PathLike)):
        return True
    raw = os.fsdecode(value).replace("/", "\\").rstrip("\\").casefold()
    if os.name == "nt" and raw in {"nul", "\\\\.\\nul", "\\\\?\\nul"}:
        return True
    path, root = canonical_io_path(value), root.resolve()
    if not path.is_relative_to(root):
        return False
    relative = path.relative_to(root).as_posix()
    if _csv_target(path):
        return _owned_table_stage(root, path)
    if relative in FROZEN_FILES:
        return False
    if path.is_relative_to(root / "ideas"):
        if path == root / "ideas":
            return True
        direct = relative
        temporary = re.fullmatch(r"\.(ideas\.md|novelty_report\.md)\.\d+\.\d+\.[a-f0-9]{32}\.tmp", path.name)
        if temporary and path.parent == root / "ideas":
            direct = "ideas/" + temporary[1]
        allowed_owner = {"ideas/ideas.md": "idea", "ideas/novelty_report.md": "novelty"}.get(direct)
        return bool(rerun_source_owners and allowed_owner and MODEL_OWNER.get() == allowed_owner)
    if any(path.is_relative_to(root / name) for name in FROZEN_DIRECTORIES):
        return False
    if path.is_relative_to(root / "literature") and not rerun_literature:
        return False
    if relative == "experiments/METHOD_CONTRACT.json" and MODEL_OWNER.get() not in {"", "exp-design"}:
        return False
    if relative.split("/", 1)[0].startswith("merak-live-settings-read-"):
        return True
    allowed = ("literature", "experiments", "figures", "paper", "review-stage", "audit-results", "slides", ".merak", ".mpl-cache")
    if path == root or any(path.is_relative_to(root / name) for name in allowed):
        return True
    return _owned_root_file(path, root)


def _continuing_runtime_files(root: Path, run_id: str) -> set[Path]:
    """Only a proven stopped exact run may retain its three mutable runtime records."""
    if not run_id:
        return set()
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError("Benchmark continuation requires its exact hexadecimal runtime run ID")
    state = json.loads((root / f".merak/runs/{run_id}.json").read_text(encoding="utf-8-sig"))
    if (not isinstance(state, dict) or state.get("schema") != 1 or state.get("run_id") != run_id
            or state.get("status") not in {"incomplete", "failed", "cancelled"}):
        raise ValueError("Only the exact stopped benchmark run can retain writable runtime records")
    return {root / f".merak/runs/{run_id}{suffix}" for suffix in (".json", ".skills.json", ".specialists.json")}


def _runtime_atomic_target(path: Path) -> Path:
    temporary = re.fullmatch(r"\.(.+)\.\d+\.\d+\.[a-f0-9]{32}\.tmp", path.name)
    return path.with_name(temporary[1]) if temporary else path


def install_benchmark_write_guard(root: Path, *, rerun_literature: bool = False,
                                  rerun_source_owners: bool = False, continuing_run_id: str = "") -> None:
    """Reject frozen writes before mutation and permit only trusted local TeX spawns."""
    from scripts.verify_offline_suite import _write_path, canonical_io_path
    from scripts.full_benchmark_runtime_records import trusted_runtime_record_target
    root = root.resolve(strict=True)
    runtime_files = _continuing_runtime_files(root, continuing_run_id)
    prior_execution_files = {path.resolve() for name in (".merak/runs", ".merak/skill-invocations")
                             for path in (root / name).glob("*.json") if path.is_file()} - runtime_files

    def check(value):
        _write_path(value, root)
        if isinstance(value, (str, bytes, os.PathLike)):
            target = _runtime_atomic_target(canonical_io_path(value))
            if target in prior_execution_files:
                raise PermissionError("New benchmark workflow cannot rewrite its imported source-run owner proof")
            if target in runtime_files and MODEL_OWNER.get() and not trusted_runtime_record_target(target):
                raise PermissionError("Benchmark lifecycle state and execution proof are runtime-owned, not model-authored")
        if not write_is_allowed(root, value, rerun_literature=rerun_literature, rerun_source_owners=rerun_source_owners):
            raise PermissionError("Full benchmark verification cannot alter frozen science, numeric rows, or foreign files")

    def audit(event, arguments):
        if event == "os.mkdir" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            directory = Path(os.fsdecode(arguments[0])).resolve()
            if directory.is_relative_to(root) and directory.is_dir():
                return
        if event == "open":
            value, mode, flags = arguments
            if isinstance(mode, str) and any(flag in mode for flag in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                check(value)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in arguments[:2]:
                check(value)
        elif event == "subprocess.Popen":
            from scripts.live_snapshot_compilation import validate_spawn_scope

            validate_spawn_scope(root, *arguments[:3])
    sys.addaudithook(audit)


def scientific_method_identity(root: Path) -> dict[str, Any]:
    """The authorized scene producer may repair visual projection, not the hypothesis."""
    payload = json.loads((root / "experiments/METHOD_CONTRACT.json").read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema") != 2:
        raise ValueError("Benchmark requires the current scientific method contract")
    from server.services.frozen_benchmark_authority import _scientific_method

    return _scientific_method(payload)


def _method_difference_summary(expected: Any, proposed: Any, limit: int = 8) -> str:
    """Name bounded changed field paths without exposing complete contract text."""
    changes: list[str] = []

    def visit(before: Any, after: Any, path: str) -> None:
        if len(changes) >= limit or before == after:
            return
        if type(before) is not type(after):
            changes.append(f"{path}: {type(before).__name__} -> {type(after).__name__}")
        elif isinstance(before, dict):
            for key in sorted(set(before) | set(after)):
                child = path + "/" + str(key)
                if key not in before:
                    changes.append(child + ": added")
                elif key not in after:
                    changes.append(child + ": removed")
                else:
                    visit(before[key], after[key], child)
                if len(changes) >= limit:
                    break
        elif isinstance(before, list):
            if len(before) != len(after):
                changes.append(f"{path}: length {len(before)} -> {len(after)}")
            for index, (old, new) in enumerate(zip(before, after)):
                visit(old, new, path + "/" + str(index))
                if len(changes) >= limit:
                    break
        else:
            old, new = json.dumps(before, ensure_ascii=True), json.dumps(after, ensure_ascii=True)
            changes.append(f"{path}: {old[:60]} -> {new[:60]}")

    visit(expected, proposed, "")
    return "; ".join(changes) or "method scientific identity differs"


def validate_method_tool_change(session: Any, tool: Any, root: Path, expected: dict[str, Any]) -> None:
    """Reject model-owned scientific changes before Write/Edit can touch the copy."""
    if tool.name not in {"Write", "Edit"}:
        return
    arguments = tool.arguments or {}
    relative = str(arguments.get("file_path") or arguments.get("path") or "")
    target = (root / relative).resolve()
    if target != root / "experiments/METHOD_CONTRACT.json":
        return
    if str(getattr(session, "workflow_node_id", "")) != "exp-design":
        raise MethodScopeViolation("Only the exp-design scene producer may edit the scientific method contract")
    text = str(arguments.get("content") or "")
    if tool.name == "Edit":
        current = target.read_text(encoding="utf-8-sig")
        old = str(arguments.get("old_text") or "")
        if not old or current.count(old) != 1:
            raise MethodScopeViolation("Method scene edit must identify one exact existing source span")
        text = current.replace(old, str(arguments.get("new_text") or ""), 1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise MethodScopeViolation(f"Method proposal is invalid JSON at line {error.lineno}, column {error.colno}") from error
    from server.services.frozen_benchmark_authority import FrozenBenchmarkAuthorityError, _scientific_method

    if not isinstance(value, dict):
        raise MethodScopeViolation("Method proposal must be a current schema-2 JSON object")
    current = json.loads(target.read_text(encoding="utf-8-sig"))
    if ("integration_verdict" in value) != ("integration_verdict" in current) or value.get("integration_verdict") != current.get("integration_verdict"):
        raise MethodScopeViolation("integration_verdict is runtime-owned; preserve the complete CURRENT object unchanged")
    try:
        proposed = _scientific_method(value)
    except FrozenBenchmarkAuthorityError as error:
        raise MethodScopeViolation(str(error)) from error
    if proposed != expected:
        raise MethodScopeViolation("Method scene repair cannot change claims, evaluations or other frozen scientific fields: "
                                   + _method_difference_summary(expected, proposed))


@contextmanager
def benchmark_method_tool_scope(engine: Any, root: Path, expected: dict[str, Any]):
    """Return known pre-write refusals to the model; unrelated failures remain fatal.

    A refused proposal never calls the normal handler, writes an artifact or
    grants acceptance. The same session may submit a different conforming edit.
    """
    original = engine._execute_tool

    async def scoped_tool(session, tool, *arguments, **keywords):
        try:
            validate_method_tool_change(session, tool, root, expected)
        except MethodScopeViolation as error:
            return engine._blocked_tool_result(tool, "METHOD_SCOPE_VIOLATION: " + str(error) + "\n" + METHOD_SCENE_GUIDANCE)
        token = MODEL_OWNER.set(str(getattr(session, "workflow_node_id", "")))
        try:
            return await original(session, tool, *arguments, **keywords)
        finally:
            MODEL_OWNER.reset(token)

    with patch.object(engine, "_execute_tool", scoped_tool):
        yield
