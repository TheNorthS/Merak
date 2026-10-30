"""Review reuse ignores compile metadata while retaining every visible page change."""

import fitz

from server.services.pdf_content_snapshot import pdf_content_snapshot
from server.workflows.audit_policy_identity import canonical_policy_digest


def test_pdf_metadata_change_keeps_review_content_identity_but_new_text_does_not(tmp_path):
    path = tmp_path / "main.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Original scientific value 0.12")
        document.save(path)
    original = pdf_content_snapshot(path)
    with fitz.open(path) as document:
        document.set_metadata({"title": "New compile metadata", "creationDate": "D:20261019000000"})
        document.saveIncr()
    assert pdf_content_snapshot(path) == original
    with fitz.open(path) as document:
        document[0].insert_text((72, 100), "Changed scientific value 0.03")
        document.saveIncr()
    assert pdf_content_snapshot(path) != original


def test_audit_policy_relocation_keeps_digest_but_instruction_edit_changes_it(tmp_path):
    left = tmp_path / "runtime-a/merak-skills/experiment-audit/SKILL.md"
    right = tmp_path / "runtime-b/merak-skills/experiment-audit/SKILL.md"
    a = f"Audit honestly. Read {left.parent.parent.as_posix()}/shared-references/evidence.md"
    b = f"Audit honestly. Read {right.parent.parent.as_posix()}/shared-references/evidence.md"
    assert canonical_policy_digest(a, str(left)) == canonical_policy_digest(b, str(right))
    assert canonical_policy_digest(a, str(left)) != canonical_policy_digest(b + " Changed policy.", str(right))
