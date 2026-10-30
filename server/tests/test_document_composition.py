"""Pure local tests for path-only large document handoff."""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from server.agent.tools.document_tools import (
    MAX_DOCUMENT_PART_CHARS,
    assemble_document,
    write_document_part,
)


def test_bounded_parts_assemble_atomically_in_declared_order(tmp_path: Path) -> None:
    target = tmp_path / "literature/survey.md"
    write_document_part(str(target), "01-intro", "# Survey\n\nIntro.", project_path=str(tmp_path))
    write_document_part(str(target), "02-body", "## Evidence\n\nBody.", project_path=str(tmp_path))

    result = assemble_document(
        str(target), ["01-intro", "02-body"], project_path=str(tmp_path),
    )

    assert "Assembled 2 parts" in result
    assert target.read_text(encoding="utf-8") == (
        "# Survey\n\nIntro.\n\n## Evidence\n\nBody.\n"
    )


def test_oversized_part_is_rejected_before_canonical_mutation(tmp_path: Path) -> None:
    target = tmp_path / "literature/survey.md"

    with pytest.raises(ValueError, match="exceeds"):
        write_document_part(
            str(target), "oversized", "x" * (MAX_DOCUMENT_PART_CHARS + 1),
            project_path=str(tmp_path),
        )

    assert not target.exists()


def test_assembly_rejects_missing_or_tampered_part(tmp_path: Path) -> None:
    target = tmp_path / "paper/main.tex"
    write_document_part(str(target), "intro", "Introduction", project_path=str(tmp_path))

    with pytest.raises(ValueError, match="missing from index"):
        assemble_document(str(target), ["intro", "method"], project_path=str(tmp_path))

    part = next((tmp_path / ".merak/composition").rglob("intro.part"))
    part.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        assemble_document(str(target), ["intro"], project_path=str(tmp_path))


def test_json_parts_are_validated_before_replacing_canonical_document(tmp_path):
    target = tmp_path / "experiments/study_metadata.json"
    target.parent.mkdir()
    target.write_text('{"old": true}', encoding="utf-8")
    write_document_part(str(target), "first", '{"name": "study",', project_path=str(tmp_path))
    with pytest.raises(json.JSONDecodeError):
        assemble_document(str(target), ["first"], project_path=str(tmp_path))
    assert json.loads(target.read_text()) == {"old": True}
    write_document_part(str(target), "second", '"seeds": [1, 2]}', project_path=str(tmp_path))
    assemble_document(str(target), ["first", "second"], project_path=str(tmp_path))
    assert json.loads(target.read_text()) == {"name": "study", "seeds": [1, 2]}


def test_json_composition_cannot_bypass_versioned_writer_contract(tmp_path):
    target = tmp_path / "experiments/METHOD_CONTRACT.json"
    write_document_part(str(target), "wrong", '{"schema": 1}', project_path=str(tmp_path))
    with pytest.raises(ValueError, match="ARTIFACT_CONTRACT_ERROR"):
        assemble_document(str(target), ["wrong"], project_path=str(tmp_path))
    assert not target.exists()
