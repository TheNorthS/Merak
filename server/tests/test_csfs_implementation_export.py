"""Export contract checks use only temporary copies and never run research code."""

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import yaml

from scripts.verify_offline_suite import REPOSITORY, verification_code_sha256
from server.services import csfs_implementation_export as export
from server.services.protocol_conformance import read_protocol_readiness


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _put(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _receipt(root):
    directory = root / "isolated-verification"
    directory.mkdir()
    tree = ET.Element("testsuites")
    suite = ET.SubElement(tree, "testsuite", tests="105", failures="0", errors="0", skipped="0")
    for name in sorted(export.TEST_FILES):
        for index in range(15):
            ET.SubElement(suite, "testcase", classname="server.tests." + Path(name).stem,
                          name=f"test_contract_fixture_{index}", time="0.001")
    report = directory / "junit.xml"
    ET.ElementTree(tree).write(report, encoding="utf-8", xml_declaration=True)
    payload = {"code_sha256": verification_code_sha256(), "code_unchanged": True, "pytest_exit_code": 0,
               "network_allowed": False, "shared_mutations_allowed": False, "excluded_test_files": [],
               "start_after": "", "stop_at": "", "shard_count": 1, "shard_index": 0,
               "selected_test_files": sorted(export.TEST_FILES), "test_files": 7, "tests": 105,
               "failures": 0, "errors": 0, "skipped": 0, "report_path": str(report)}
    path = directory / "offline-summary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, report, payload


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "live-verification-106-bush5hv6"
    authority = REPOSITORY / "live-verification-106-bush5hv6"
    for name in ("experiments/EXPERIMENT_PLAN.md", "ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json"):
        _put(root, name, (authority / name).read_bytes())
    for name, content in {
        "experiments/src/data.py": b"# Historical nonconformant source; never execute during export.\n",
        "experiments/src/train.py": b"# Historical entrypoint must be archived, not reused.\n",
        "experiments/IMPLEMENTATION_BLUEPRINT.json": b'{"status":"old_frozen_blueprint"}',
        "experiments/IMPLEMENTATION_BUILD.json": b'{"status":"old_completed_build"}',
        "experiments/PROTOCOL_CONFORMANCE.json": b'{"schema":1,"status":"mismatch","cannot_execute":true}',
        "experiments/RUN_SPEC.json": b'{"schema":1,"implementation_status":"integration_ready"}',
        "experiments/configs/main.yaml": b'research_contract:\n  execution_authorized: false\n',
        ".merak/runs/3de990b9ec00.json": b'{"schema":1,"phases":{"exp-design":{"status":"accepted"}}}',
        ".merak/runs/3de990b9ec00.skills.json": b'{"schema":2,"stages":{"paper":{"status":"completed"}}}',
    }.items():
        _put(root, name, content)
    for index in range(22):
        _put(root, f"experiments/results/simulated/fixture-{index}.csv", f"row,value\ntemporary-{index},{index}\n".encode())
    return root


def test_complete_current_receipt_is_validated_directly_not_mocked_as_passing(tmp_path):
    receipt, report, _payload = _receipt(tmp_path)
    evidence = export._receipt(receipt, REPOSITORY)
    assert evidence["receipt_sha256"] == _sha(receipt) and evidence["junit_sha256"] == _sha(report)
    assert evidence["tests"] == 105 and evidence["test_files"] == sorted(export.TEST_FILES)


@pytest.mark.parametrize("field,value", [("code_sha256", "0" * 64), ("code_unchanged", False),
    ("pytest_exit_code", 1), ("network_allowed", True), ("shared_mutations_allowed", True),
    ("excluded_test_files", ["test_csfs_v1_data.py"]), ("start_after", "some-test"),
    ("stop_at", "some-test"), ("shard_count", 2), ("shard_index", 1), ("test_files", 6), ("tests", 999)])
def test_stale_filtered_partial_or_false_count_receipts_never_attest_code_readiness(tmp_path, field, value):
    receipt, _report, payload = _receipt(tmp_path)
    payload[field] = value
    receipt.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        export._receipt(receipt, REPOSITORY)


@pytest.mark.parametrize("defect", ["missing_file", "duplicate_file", "failed", "skipped", "error", "header_only", "wrong_identity"])
def test_real_junit_structure_and_each_protocol_file_are_required_not_only_a_hundred_case_header(tmp_path, defect):
    receipt, report, payload = _receipt(tmp_path)
    if defect in {"missing_file", "duplicate_file"}:
        payload["selected_test_files"] = payload["selected_test_files"][:-1]
        if defect == "duplicate_file":
            payload["selected_test_files"] = sorted(export.TEST_FILES) + [sorted(export.TEST_FILES)[0]]
        receipt.write_text(json.dumps(payload))
    else:
        tree = ET.parse(report)
        suite = tree.getroot().find("testsuite")
        if defect == "header_only":
            for case in list(suite):
                suite.remove(case)
        elif defect == "wrong_identity":
            for case in suite:
                case.set("classname", "server.tests.unrelated_tests")
        else:
            key = {"failed": "failure", "skipped": "skipped", "error": "error"}[defect]
            ET.SubElement(suite[0], key, message="Actual verification was not a complete pass")
        tree.write(report, encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError):
        export._receipt(receipt, REPOSITORY)


def test_foreign_junit_cannot_be_attached_to_an_otherwise_current_local_receipt(tmp_path):
    receipt, report, payload = _receipt(tmp_path)
    foreign = tmp_path / "unrelated.xml"
    foreign.write_bytes(report.read_bytes())
    payload["report_path"] = str(foreign)
    receipt.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        export._receipt(receipt, REPOSITORY)


@pytest.mark.parametrize("payload", [[], None, "untyped receipt"])
def test_unsupported_receipt_shape_is_a_typed_rejection_not_an_unexpected_parser_crash(tmp_path, payload):
    receipt, _report, _value = _receipt(tmp_path)
    receipt.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        export._receipt(receipt, REPOSITORY)


def test_hardlinked_junit_is_not_independent_local_test_evidence(tmp_path):
    receipt, report, _payload = _receipt(tmp_path)
    (report.parent / "shared-junit.xml").hardlink_to(report)
    with pytest.raises(ValueError):
        export._receipt(receipt, REPOSITORY)


def test_exact_accepted_authority_is_readonly_and_unknown_plan_is_not_guessed(source):
    before = _files(source)
    value = export._authority(source)
    assert value["plan_sha256"] == "46fe8c696075b6ad1cf8e80d22a280d09198f49f8343e60a0d261e3873a488c7"
    assert _files(source) == before
    path = source / "experiments/EXPERIMENT_PLAN.md"
    path.write_bytes(path.read_bytes() + b"\nDifferent registered protocol\n")
    with pytest.raises(ValueError):
        export._authority(source)


def test_copied_plan_does_not_authorize_an_unrelated_schema_two_selected_idea(source):
    path = source / "ideas/SELECTED_IDEA.json"
    selected = json.loads(path.read_text(encoding="utf-8-sig"))
    selected["title"] = "Unrelated scientific proposal"
    path.write_text(json.dumps(selected), encoding="utf-8")
    with pytest.raises(ValueError):
        export._authority(source)


def test_exported_package_has_exact_tested_source_bytes_and_only_one_active_entrypoint(tmp_path):
    hashes = export._export_sources(tmp_path)
    package = REPOSITORY / "server/experiment_protocols/csfs_v1"
    for source in package.glob("*.py"):
        target = tmp_path / "experiments/src/csfs_v1" / source.name
        assert target.read_bytes() == source.read_bytes()
        assert hashes[target.relative_to(tmp_path).as_posix()] == _sha(target)
    assert (tmp_path / "experiments/src/train.py").is_file()
    assert (tmp_path / "experiments/src/csfs_v1/cli.py").is_file()
    assert (tmp_path / "experiments/src/csfs_v1/persistence.py").is_file()


def test_missing_trusted_package_inventory_fails_before_claiming_exported_implementation(tmp_path, monkeypatch):
    empty_server = tmp_path / "missing-server"
    empty_server.mkdir()
    monkeypatch.setattr(export, "server_source_root", lambda: empty_server)
    with pytest.raises(ValueError):
        export._export_sources(tmp_path / "destination")


def test_new_isolated_export_preserves_all_old_raw_csvs_negative_ledger_and_source_bytes_without_new_acceptance(source, tmp_path):
    receipt, _report, _payload = _receipt(tmp_path)
    before = _files(source)
    result = export.export_csfs_reference(source, receipt, tmp_path)
    destination = Path(result["project_path"])
    assert destination.parent == tmp_path and destination.name.startswith("protocol-implementation-106-")
    assert destination != source and _files(source) == before
    raw = {name: content for name, content in before.items() if name.endswith(".csv")}
    assert len(raw) == 22 and all((destination / name).read_bytes() == content for name, content in raw.items())
    old_ledger = destination / ".merak/implementation-history/experiments/PROTOCOL_CONFORMANCE.json"
    assert old_ledger.read_bytes() == before["experiments/PROTOCOL_CONFORMANCE.json"]
    readiness = read_protocol_readiness(destination)
    assert readiness.status == "unvalidated" and readiness.cannot_execute
    assert readiness.research_evidence is readiness.implementation_matches_protocol is False
    for field in ("scientific_execution_performed", "training_performed", "research_evidence", "experiment_authorized", "old_workflow_acceptance_reused"):
        assert result[field] is False
    assert result["code_ready_verified"] is True and result["data_and_resources_still_required"] is True
    assert not (destination / "experiments/src/data.py").exists()
    assert (destination / ".merak/implementation-history/experiments/src/data.py").read_bytes() == before["experiments/src/data.py"]
    for relative in ("experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", "experiments/configs/main.yaml"):
        assert (destination / ".merak/implementation-history" / relative).read_bytes() == before[relative]
    config = yaml.safe_load((destination / "experiments/configs/main.yaml").read_text())
    assert config["research_contract"]["execution_authorized"] is False and config["execution"]["execution_prohibited_in_this_stage"] is True
    assert config["execution"]["resources"] is None
    assert config["research_contract"]["protocol_conformance_path"] == "experiments/PROTOCOL_CONFORMANCE.json"
    assert not (destination / ".merak/runs/3de990b9ec00.json").exists()
    assert not (destination / "experiments/IMPLEMENTATION_BUILD.json").exists()


def test_copy_and_receipt_owner_are_checked_before_creating_any_export_destination(source, tmp_path):
    receipt, _report, payload = _receipt(tmp_path)
    payload["code_sha256"] = "0" * 64
    receipt.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        export.export_csfs_reference(source, receipt, tmp_path)
    assert list(tmp_path.glob("protocol-implementation-106-*")) == []
    with pytest.raises(ValueError):
        export.export_csfs_reference(source, receipt, source)


@pytest.mark.parametrize("drift", ["source", "copied_csv"])
def test_mid_export_source_or_copied_csv_drift_never_produces_a_success_attestation(source, tmp_path, monkeypatch, drift):
    receipt, _report, _payload = _receipt(tmp_path)
    original_copy = export.shutil.copy2
    before = _files(source)
    modified = []

    def changed_copy(origin, target, *args, **kwargs):
        result = original_copy(origin, target, *args, **kwargs)
        origin, target = Path(origin), Path(target)
        if not modified and origin.is_relative_to(source) and origin.suffix == ".csv":
            changed = origin if drift == "source" else target
            changed.write_bytes(changed.read_bytes() + b"injected-drift,999\n")
            modified.append(changed)
        return result

    monkeypatch.setattr(export.shutil, "copy2", changed_copy)
    with pytest.raises(ValueError, match="source project changed|quantitative results"):
        export.export_csfs_reference(source, receipt, tmp_path)
    assert len(modified) == 1
    assert all(not (path / "experiments/CODE_IMPLEMENTATION_ATTESTATION.json").exists()
               for path in tmp_path.glob("protocol-implementation-106-*"))
    if drift == "copied_csv":
        assert _files(source) == before
