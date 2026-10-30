"""Fail when code-size debt grows or a new oversized module appears."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __package__:
    from .current_contract_checks import current_contract_findings
else:
    from current_contract_checks import current_contract_findings


SOURCE_ROOTS = ("server", "src", "electron", "scripts")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"}
IGNORED_PARTS = {
    "dist",
    "dist-electron",
    "node_modules",
    ".pytest_cache",
    "coverage",
}


@dataclass(frozen=True)
class Finding:
    path: str
    lines: int
    limit: int
    baseline: int | None
    reason: str


def physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if (
                path.is_file()
                and path.suffix in SOURCE_SUFFIXES
                and not IGNORED_PARTS.intersection(path.parts)
                and path.name != "check_code_standards.py"
            ):
                files.append(path)
    return sorted(files)


def evaluate(root: Path, *, strict: bool) -> tuple[list[Finding], list[Finding]]:
    baseline_path = root / "docs" / "code-size-baseline.json"
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = {
        str(path): int(lines)
        for path, lines in dict(baseline_payload.get("files") or {}).items()
    }
    class_baseline = {
        str(name): int(lines)
        for name, lines in dict(baseline_payload.get("classes") or {}).items()
    }
    function_baseline = {
        str(name): int(lines)
        for name, lines in dict(baseline_payload.get("functions") or {}).items()
    }
    production_limit = int(baseline_payload["production_limit"])
    test_limit = int(baseline_payload["test_limit"])
    class_limit = int(baseline_payload["class_limit"])
    function_limit = int(baseline_payload["function_limit"])
    failures: list[Finding] = []
    debt: list[Finding] = []

    observed: set[str] = set()
    observed_classes: set[str] = set()
    observed_functions: set[str] = set()
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        observed.add(relative)
        lines = physical_lines(path)
        limit = test_limit if is_test(path) else production_limit
        previous = baseline.get(relative)
        if lines > limit:
            finding = Finding(
                path=relative,
                lines=lines,
                limit=limit,
                baseline=previous,
                reason=(
                    "new oversized file"
                    if previous is None
                    else "oversized legacy file grew"
                    if lines > previous
                    else "legacy size debt"
                ),
            )
            debt.append(finding)
            if previous is None or lines > previous or strict:
                failures.append(finding)

        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as error:
            failures.append(Finding(
                path=relative,
                lines=int(error.lineno or 0),
                limit=0,
                baseline=None,
                reason=f"Python syntax error: {error.msg}",
            ))
            continue
        if is_test(path):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = int(getattr(node, "end_lineno", node.lineno) - node.lineno + 1)
            if isinstance(node, ast.ClassDef):
                identity = f"{relative}::{node.name}"
                observed_classes.add(identity)
                previous_symbol_size = class_baseline.get(identity)
                if size <= class_limit:
                    continue
                symbol_finding = Finding(
                    path=identity,
                    lines=size,
                    limit=class_limit,
                    baseline=previous_symbol_size,
                    reason=(
                        "new oversized class"
                        if previous_symbol_size is None
                        else "oversized legacy class grew"
                        if size > previous_symbol_size
                        else "legacy class size debt"
                    ),
                )
                debt.append(symbol_finding)
                if previous_symbol_size is None or size > previous_symbol_size or strict:
                    failures.append(symbol_finding)
            else:
                identity = f"{relative}::{node.name}"
                observed_functions.add(identity)
                previous_symbol_size = function_baseline.get(identity)
                if size <= function_limit:
                    continue
                if (not strict and lines > limit and previous is not None
                        and previous_symbol_size is None):
                    # Oversized legacy files are frozen by their file and class
                    # baselines. Their function-level debt is addressed during
                    # extraction without duplicating hundreds of exceptions.
                    continue
                symbol_finding = Finding(
                    path=identity,
                    lines=size,
                    limit=function_limit,
                    baseline=previous_symbol_size,
                    reason=(
                        "new oversized function"
                        if previous_symbol_size is None
                        else "oversized legacy function grew"
                        if size > previous_symbol_size
                        else "legacy function size debt"
                    ),
                )
                debt.append(symbol_finding)
                if previous_symbol_size is None or size > previous_symbol_size or strict:
                    failures.append(symbol_finding)

    stale_entries = sorted(set(baseline) - observed)
    for relative in stale_entries:
        failures.append(Finding(
            path=relative,
            lines=0,
            limit=test_limit if "/tests/" in f"/{relative}" else production_limit,
            baseline=baseline[relative],
            reason="stale baseline entry; remove it after the file is deleted or split",
        ))
    for identity in sorted(set(class_baseline) - observed_classes):
        failures.append(Finding(
            path=identity,
            lines=0,
            limit=class_limit,
            baseline=class_baseline[identity],
            reason="stale class baseline entry; remove it after extraction",
        ))
    for identity in sorted(set(function_baseline) - observed_functions):
        failures.append(Finding(
            path=identity,
            lines=0,
            limit=function_limit,
            baseline=function_baseline[identity],
            reason="stale function baseline entry; remove it after extraction",
        ))
    for relative, line, reason in current_contract_findings(root, source_files(root)):
        failures.append(Finding(
            path=relative, lines=line, limit=0, baseline=None, reason=reason,
        ))
    return failures, debt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on all existing oversize debt, not only regressions",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    failures, debt = evaluate(root, strict=args.strict)

    if args.json:
        print(json.dumps({
            "passed": not failures,
            "failures": [asdict(item) for item in failures],
            "remaining_debt": [asdict(item) for item in debt],
        }, ensure_ascii=False, indent=2))
    else:
        for item in failures:
            baseline = "new" if item.baseline is None else str(item.baseline)
            print(
                f"FAIL {item.path}: {item.lines} lines; limit={item.limit}; "
                f"baseline={baseline}; {item.reason}"
            )
        print(
            f"Code standards: {'PASS' if not failures else 'FAIL'}; "
            f"remaining size-debt items={len(debt)}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
