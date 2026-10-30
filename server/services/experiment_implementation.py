"""Audit implementation depth and frozen-method reachability from project source.

Static evidence is not a training result; scientific execution remains a
separate, explicitly authorized workflow responsibility."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from .implementation_graph import (
    call_names, definition_nodes, reachable_graph, reachable_nodes_source,
)
from .implementation_audit import audit_result
from ..contracts.entrypoints import python_entrypoint_refs


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_flatten_text(child)}" for key, child in value.items()
        )
    if isinstance(value, list):
        return " ".join(_flatten_text(child) for child in value)
    return str(value or "")


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


class ExperimentImplementationService:
    """Deterministically reject executable-method claims backed by scaffolds.

    This audit does not decide whether a scientific idea is good.  It checks
    whether a contract that says ``implemented`` is connected to a runnable
    computational path instead of merely naming classes and validators.
    """

    _IMPLEMENTED = {"implemented", "ready", "complete"}
    _SCAFFOLD_MARKERS = re.compile(
        r"(?:code.?check|static.?check|dry.?run|scaffold|planned|no.?run|"
        r"execution.?prohibited|do.?not.?run)",
        re.IGNORECASE,
    )
    # These markers describe the implementation itself, not whether an
    # experiment happened to execute in the current workflow.  A run may
    # truthfully remain ``not_executed`` during exp-design, but a contract that
    # simultaneously claims ``implemented`` and declares its scientific path
    # blocked/unreachable/incomplete is internally contradictory.
    _BLOCKED_IMPLEMENTATION_MARKERS = re.compile(
        r"(?:integration.?blocked|implementation.?blocked|unreachable|"
        r"not.?reachable|incomplete.?implementation|partial.?implementation|"
        r"missing.?integration|scaffold.?only)",
        re.IGNORECASE,
    )
    _ML_MARKERS = re.compile(
        r"(?:torch|tensorflow|keras|jax|flax|pytorch|neural|encoder|decoder|"
        r"contrastive|classification|classifier|auroc|accuracy|f1|brier|ece|"
        r"embedding|backbone|fine.?tun|pretrain)",
        re.IGNORECASE,
    )
    _STATIC_SYMBOL = re.compile(
        r"^(?:test_|validate_|verify_|check_|require$|resolved_config$|"
        r"run_preflight$|preflight$|is_number$)",
        re.IGNORECASE,
    )
    _relative = staticmethod(_relative)
    _flatten_text = staticmethod(_flatten_text)

    @staticmethod
    def _entrypoints(root: Path, run_spec: dict[str, Any]) -> list[Path]:
        """Resolve every declared project-local execution entrypoint."""
        raw_values: list[str] = []
        for key in (
            "entrypoint",
            "evaluation_entrypoint",
            "preflight_entrypoint",
            "integration_entrypoint",
            "command",
            "execution_command",
            "scientific_command",
            "evaluation_command",
            "preflight_command",
            "bounded_integration_test_command",
            "static_check_command",
        ):
            value = str(run_spec.get(key) or "").strip()
            if value:
                raw_values.append(value)
        integration = run_spec.get("integration_contract")
        if isinstance(integration, dict):
            for key in (
                "command",
                "bounded_test",
                "bounded_test_command",
                "test_command",
            ):
                value = str(integration.get(key) or "").strip()
                if value:
                    raw_values.append(value)
        matrix = run_spec.get("execution_matrix")
        if isinstance(matrix, dict):
            for key in ("command", "execution_command", "training_command", "run_command"):
                value = str(matrix.get(key) or "").strip()
                if value:
                    raw_values.append(value)

        candidates: list[Path] = []
        for ref in python_entrypoint_refs(raw_values):
            try:
                candidate = ref.resolve(root)
            except ValueError:
                continue
            if candidate.is_file() and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    @classmethod
    def _entrypoint(cls, root: Path, run_spec: dict[str, Any]) -> Path | None:
        entrypoints = cls._entrypoints(root, run_spec)
        return entrypoints[0] if entrypoints else None

    @staticmethod
    def _definition_nodes(tree: ast.Module) -> dict[str, ast.AST]:
        return definition_nodes(tree)

    @staticmethod
    def _call_names(node: ast.AST) -> set[str]:
        return call_names(node)

    @classmethod
    def _reachable_graph(
        cls,
        trees: dict[Path, ast.Module],
        entrypoint: Path | None,
    ) -> tuple[set[str], list[ast.AST]]:
        return reachable_graph(trees, entrypoint)
    @staticmethod
    def _nodes_source(nodes: list[ast.AST]) -> str:
        return reachable_nodes_source(nodes)

    @staticmethod
    def _source_capabilities(source: str) -> dict[str, bool]:
        from .implementation_capabilities import source_capabilities
        return source_capabilities(source)

    @staticmethod
    def _definition_is_substantive(node: ast.AST) -> bool:
        body = list(getattr(node, "body", []) or [])
        meaningful = [
            item for item in body
            if not (
                isinstance(item, ast.Expr)
                and isinstance(item.value, ast.Constant)
                and isinstance(item.value.value, str)
            )
        ]
        if not meaningful:
            return False
        if all(isinstance(item, (ast.Pass, ast.Raise)) for item in meaningful):
            return False
        if len(meaningful) == 1 and isinstance(meaningful[0], ast.Return):
            value = meaningful[0].value
            if value is None or isinstance(value, ast.Constant):
                return False
        return True

    @classmethod
    def audit(
        cls,
        project_path: str | Path,
        method_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        method = dict(
            method_contract
            or _json(root / "experiments" / "METHOD_CONTRACT.json")
        )
        run_spec = _json(root / "experiments" / "RUN_SPEC.json")
        return audit_result(cls, root, method, run_spec)



experiment_implementation_service = ExperimentImplementationService()
