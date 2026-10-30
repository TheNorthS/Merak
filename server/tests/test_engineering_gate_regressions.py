"""Pure fixture regressions for engineering gates, never workflow execution."""

import json
from pathlib import Path

from scripts.check_code_standards import evaluate
from scripts.current_contract_checks import current_contract_findings


def _fixture_repo(root: Path, files: dict[str, int] | None = None) -> None:
    (root / "docs").mkdir()
    (root / "server").mkdir()
    (root / "docs" / "code-size-baseline.json").write_text(
        json.dumps(
            {
                "production_limit": 800,
                "test_limit": 1200,
                "class_limit": 500,
                "function_limit": 80,
                "files": files or {},
                "classes": {},
                "functions": {},
            }
        ),
        encoding="utf-8",
    )


def test_syntax_errors_fail_the_gate_instead_of_being_skipped(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    (tmp_path / "server" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    failures, _ = evaluate(tmp_path, strict=False)

    assert len(failures) == 1
    assert failures[0].reason.startswith("Python syntax error:")


def test_test_file_syntax_errors_also_fail_the_gate(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    tests = tmp_path / "server" / "tests"
    tests.mkdir()
    (tests / "test_broken.py").write_text("def broken(:\n", encoding="utf-8")

    failures, _ = evaluate(tmp_path, strict=False)

    assert failures[0].path == "server/tests/test_broken.py"
    assert failures[0].reason.startswith("Python syntax error:")


def test_reduced_file_baseline_cannot_hide_an_oversized_function(
    tmp_path: Path,
) -> None:
    _fixture_repo(tmp_path, {"server/reduced.py": 2000})
    source = "def large():\n" + "    value = 1\n" * 81
    (tmp_path / "server" / "reduced.py").write_text(source, encoding="utf-8")

    failures, _ = evaluate(tmp_path, strict=False)

    assert failures[0].path == "server/reduced.py::large"


def test_strict_mode_reports_function_debt_in_oversized_legacy_files(
    tmp_path: Path,
) -> None:
    _fixture_repo(tmp_path, {"server/legacy.py": 2000})
    source = "def large():\n" + "    value = 1\n" * 900
    (tmp_path / "server" / "legacy.py").write_text(source, encoding="utf-8")

    failures, _ = evaluate(tmp_path, strict=True)

    assert {item.path for item in failures} == {
        "server/legacy.py",
        "server/legacy.py::large",
    }


def test_retired_adapter_symbol_fails_current_contract_guard(tmp_path: Path) -> None:
    source = tmp_path / "server/workflows/engine.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def _canonicalize_node_artifacts():\n    return None\n", encoding="utf-8",
    )

    assert current_contract_findings(tmp_path, [source]) == [(
        "server/workflows/engine.py", 1,
        "retired contract adapter reintroduced: _canonicalize_node_artifacts",
    )]


def test_artifact_alias_entry_fails_current_contract_guard(tmp_path: Path) -> None:
    source = tmp_path / "server/services/project_scaffold.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'WORKFLOW_ARTIFACT_CONTRACT = {"idea": {"aliases": {}}}\n'
        'def get_workflow_artifact_contract():\n    return {}\n',
        encoding="utf-8",
    )

    assert current_contract_findings(tmp_path, [source]) == [(
        "server/services/project_scaffold.py", 1,
        "artifact aliases are prohibited",
    )]


def test_method_contract_schema_downgrade_fails_current_contract_guard(
    tmp_path: Path,
) -> None:
    source = tmp_path / "server/services/method_contract_persistence.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'def finalize(payload):\n    payload["schema"] = 1\n',
        encoding="utf-8",
    )

    assert current_contract_findings(tmp_path, [source]) == [(
        "server/services/method_contract_persistence.py",
        2,
        "method contract writer must use METHOD_CONTRACT_SCHEMA",
    )]


def test_node_execution_uses_workflow_owned_effort_prompt() -> None:
    """Catch moved-symbol import errors before a real workflow starts."""
    from server.workflows.effort_config import build_effort_prompt_section as owner
    from server.workflows.node_execution_phases import (
        build_effort_prompt_section as consumer,
    )

    assert consumer is owner
    assert "Effort level" in consumer("balanced", "draft")
