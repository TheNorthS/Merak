"""Review and audit hash canonical packaged source, never absent loaded .py paths."""

from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

from server.utils import runtime_source_root
from server.workflows.review_audit import audit_runtime_attestation
from server.workflows.review_policy_fingerprint import review_policy_fingerprint


def test_review_and_audit_identity_survive_frozen_relocation_and_detect_real_changes(tmp_path, monkeypatch):
    root = runtime_source_root.server_source_root()
    monkeypatch.setenv("MERAK_SKILLS_PATH", str(root.parent / "merak-skills"))
    context = SimpleNamespace(difficulty="hard", delivery_goal="reviewable_draft",
                              evidence_mode="synthetic_preview", researcher_feedback="")
    before_review = review_policy_fingerprint(context)
    before_audit = audit_runtime_attestation()
    assert all(value != "missing" for value in before_audit["components"].values())
    mirror = tmp_path / "merak-source/server"
    for source in root.rglob("*.py"):
        if "tests" in source.relative_to(root).parts:
            continue
        target = mirror / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(runtime_source_root, "__file__", str(tmp_path / "server/utils/runtime_source_root.py"))
    assert not (tmp_path / "server/workflows/review_loop.py").exists()
    assert review_policy_fingerprint(context) == before_review
    assert audit_runtime_attestation() == before_audit
    target = mirror / "workflows/review_loop.py"
    target.write_bytes(target.read_bytes() + b"\n# Changed review implementation\n")
    assert review_policy_fingerprint(context) != before_review
    target = mirror / "workflows/audit_protocol.py"
    target.write_bytes(target.read_bytes() + b"\n# Changed audit implementation\n")
    assert audit_runtime_attestation()["signature"] != before_audit["signature"]
