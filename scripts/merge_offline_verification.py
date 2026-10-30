"""Attest only disjoint, passing offline shards covering the complete inventory."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_offline_suite import REPOSITORY, verification_code_sha256


def merge_receipts(paths: list[Path], output: Path) -> dict:
    current = verification_code_sha256()
    inventory = {path.name for path in (REPOSITORY / "server/tests").glob("test_*.py")}
    observed: set[str] = set()
    indexes: set[int] = set()
    combined = ET.Element("testsuites")
    for path in paths:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (receipt.get("pytest_exit_code") != 0 or receipt.get("code_sha256") != current
                or receipt.get("code_unchanged") is not True or receipt.get("excluded_test_files")
                or receipt.get("start_after") or receipt.get("stop_at")
                or receipt.get("network_allowed") is not False or receipt.get("shared_mutations_allowed") is not False
                or receipt.get("shard_count") != len(paths) or receipt.get("shard_index") in indexes):
            raise ValueError("Offline shard is failed, stale, filtered or not uniquely identified")
        selected = receipt.get("selected_test_files")
        if not isinstance(selected, list) or len(selected) != receipt.get("test_files") or not selected:
            raise ValueError("Offline shard has no exact test-file inventory")
        if len(set(selected)) != len(selected) or observed.intersection(selected):
            raise ValueError("Offline shard inventory contains duplicated or overlapping test files")
        observed.update(selected)
        indexes.add(receipt["shard_index"])
        suites = ET.parse(receipt["report_path"]).getroot().findall("testsuite")
        if (not suites or any(int(suite.get("failures", "0")) or int(suite.get("errors", "0")) for suite in suites)
                or sum(int(suite.get("tests", "0")) for suite in suites) < len(selected)):
            raise ValueError("Offline shard JUnit evidence is incomplete or contains failures")
        for suite in suites:
            combined.append(copy.deepcopy(suite))
    if observed != inventory or indexes != set(range(len(paths))):
        raise ValueError("Offline shards do not cover the complete current repository exactly once")
    report = output.with_suffix(".junit.xml")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(combined).write(report, encoding="utf-8", xml_declaration=True)
    result = {"pytest_exit_code": 0, "report_path": str(report.resolve()), "test_files": len(inventory),
              "selected_test_files": sorted(inventory), "excluded_test_files": [], "start_after": "", "stop_at": "",
              "code_sha256": current, "code_unchanged": True, "network_allowed": False,
              "shared_mutations_allowed": False, "verified_shards": [str(path.resolve()) for path in paths]}
    result.update({name: sum(int(suite.get(name, "0")) for suite in combined)
                   for name in ("tests", "failures", "errors", "skipped")})
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(merge_receipts(options.receipt, options.output)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
