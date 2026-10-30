"""Complete offline receipts cannot hide missing, overlapping or failed shards."""

import json
from pathlib import Path

import pytest

from scripts import merge_offline_verification as merge


def _fixtures(root, monkeypatch):
    repo = root / "repository"
    (repo / "server/tests").mkdir(parents=True)
    for name in ("test_one.py", "test_two.py"):
        (repo / "server/tests" / name).write_text("# fixture")
    monkeypatch.setattr(merge, "REPOSITORY", repo)
    monkeypatch.setattr(merge, "verification_code_sha256", lambda: "current-test-source")
    paths = []
    for index, name in enumerate(("test_one.py", "test_two.py")):
        report = root / f"shard-{index}.xml"
        report.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>')
        receipt = root / f"receipt-{index}.json"
        receipt.write_text(json.dumps({"pytest_exit_code": 0, "code_sha256": "current-test-source", "code_unchanged": True,
                                      "network_allowed": False, "shared_mutations_allowed": False, "excluded_test_files": [],
                                      "start_after": "", "stop_at": "", "shard_count": 2, "shard_index": index,
                                      "test_files": 1, "selected_test_files": [name], "report_path": str(report)}))
        paths.append(receipt)
    return paths


def test_all_disjoint_current_shards_prove_the_entire_inventory(tmp_path, monkeypatch):
    receipts = _fixtures(tmp_path, monkeypatch)
    result = merge.merge_receipts(receipts, tmp_path / "complete.json")
    assert result["test_files"] == 2 and result["tests"] == 2
    assert result["failures"] == result["errors"] == 0


@pytest.mark.parametrize("defect", ["missing_file", "overlap", "failed", "stale", "filtered", "duplicate_shard"])
def test_incomplete_or_invalid_shards_cannot_grant_paid_execution(tmp_path, monkeypatch, defect):
    receipts = _fixtures(tmp_path, monkeypatch)
    payload = json.loads(receipts[1].read_text())
    if defect in {"missing_file", "overlap"}:
        payload["selected_test_files"] = ["test_absent.py" if defect == "missing_file" else "test_one.py"]
    elif defect == "failed":
        Path(payload["report_path"]).write_text('<testsuites><testsuite tests="1" failures="1" errors="0"/></testsuites>')
    elif defect == "stale":
        payload["code_sha256"] = "old-source"
    elif defect == "filtered":
        payload["excluded_test_files"] = ["test_one.py"]
    else:
        payload["shard_index"] = 0
    receipts[1].write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        merge.merge_receipts(receipts, tmp_path / "must-not-exist.json")
    assert not (tmp_path / "must-not-exist.json").exists()
