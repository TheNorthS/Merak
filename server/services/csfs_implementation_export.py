"""Explicitly selected CSFS-v1 code export; no researcher-state promotion or execution.

Only this accepted protocol is supported by this exporter. It is not a generic
EEG replacement and is never selected automatically by domain or filename.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from ..utils.runtime_source_root import server_source_root
from ..experiment_protocols.csfs_v1.protocol import registered_configuration


TEST_FILES = frozenset({"test_csfs_v1_data.py", "test_csfs_v1_models.py", "test_csfs_v1_statistics.py",
                        "test_csfs_v1_training_policy.py", "test_csfs_v1_execution_safety.py",
                        "test_csfs_v1_study_path.py", "test_csfs_implementation_export.py"})


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(path: Path, repository: Path) -> dict:
    from scripts.verify_offline_suite import verification_code_sha256

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Protocol test receipt must be object-shaped current evidence")
    if (value.get("code_sha256") != verification_code_sha256() or value.get("code_unchanged") is not True
            or value.get("pytest_exit_code") != 0 or value.get("network_allowed") is not False
            or value.get("shared_mutations_allowed") is not False or value.get("excluded_test_files")
            or value.get("start_after") or value.get("stop_at") or value.get("shard_count") != 1
            or value.get("shard_index") != 0 or value.get("test_files") != len(TEST_FILES)
            or len(value.get("selected_test_files") or ()) != len(TEST_FILES)
            or set(value.get("selected_test_files") or ()) != TEST_FILES):
        raise ValueError("CSFS export requires the complete current, passing, unfiltered protocol test receipt")
    report_path = Path(value["report_path"])
    if (report_path.resolve().parent != path.resolve().parent or report_path.is_symlink()
            or report_path.stat().st_nlink > 1 or any(parent.is_symlink() for parent in report_path.parents)):
        raise ValueError("Protocol JUnit must be the direct owned receipt sibling, not a linked or foreign report")
    suites = ET.parse(report_path).getroot().findall("testsuite")
    count = sum(int(suite.get("tests", "0")) for suite in suites)
    cases = [case for suite in suites for case in suite.findall("testcase")]
    covered = {str(case.get("classname", "")).rsplit(".", 1)[-1] + ".py"
               for suite in suites for case in suite.findall("testcase")}
    if (not suites or any(int(suite.get(name, "0")) for suite in suites for name in ("failures", "errors", "skipped"))
            or count < 100 or count != len(cases) or value.get("tests") != count or covered != TEST_FILES
            or any(case.find(name) is not None for case in cases for name in ("failure", "error", "skipped"))):
        raise ValueError("CSFS test receipt has missing cases, failed checks, or skipped protocol verification")
    return {"receipt_sha256": _hash(path), "junit_sha256": _hash(report_path),
            "code_sha256": value["code_sha256"], "tests": value["tests"], "test_files": sorted(TEST_FILES)}


def _authority(root: Path) -> dict:
    plan = root / "experiments/EXPERIMENT_PLAN.md"
    selected = json.loads((root / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8-sig"))
    if (not plan.is_file() or _hash(plan) != "46fe8c696075b6ad1cf8e80d22a280d09198f49f8343e60a0d261e3873a488c7"
            or selected.get("schema") != 2
            or _hash(root / "ideas/SELECTED_IDEA.json") != "f84a8cbdbbc0e6384276174fcb9f614f93a4e6e69907efe79bbb629325280056"):
        raise ValueError("CSFS reference export is restricted to its exact explicitly authorized registered protocol")
    return {"plan_sha256": _hash(plan), "selected_idea_sha256": _hash(root / "ideas/SELECTED_IDEA.json")}


def _export_sources(destination: Path) -> dict[str, str]:
    package = server_source_root() / "experiment_protocols/csfs_v1"
    required = {"__init__.py", "protocol.py", "data_contract.py", "preprocessing.py", "data.py",
        "perturbations.py", "models.py", "objectives.py", "baselines.py", "capacity.py", "metrics.py",
        "statistics.py", "evaluation.py", "training.py", "training_policy.py", "training_state.py",
        "execution_io.py", "execution_safety.py", "checkpoint_contract.py", "persistence.py", "study.py", "cli.py"}
    if {path.name for path in package.glob("*.py")} != required:
        raise ValueError("The trusted CSFS package inventory is incomplete or has unknown active modules")
    copied = {}
    for source in sorted(package.glob("*.py")):
        ast.parse(source.read_text(encoding="utf-8-sig"), filename=source.name)
        target = destination / "experiments/src/csfs_v1" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if source.read_bytes() != target.read_bytes():
            raise ValueError("Exported scientific implementation differs from the trusted tested producer")
        copied[target.relative_to(destination).as_posix()] = _hash(target)
    atomic_write_text(destination / "experiments/src/train.py",
        '"""Explicit CSFS-v1 entrypoint; importing this file never trains."""\n'
        'from csfs_v1.cli import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n')
    copied["experiments/src/train.py"] = _hash(destination / "experiments/src/train.py")
    return copied


def _configuration(root: Path) -> None:
    configuration = {"protocol": registered_configuration(),
        "research_contract": {"implementation_status": "code_verified_not_executed",
                              "execution_authorized": False, "forbid_incomplete_implementation_as_evidence": True,
                              "protocol_conformance_path": "experiments/PROTOCOL_CONFORMANCE.json"},
        "execution": {"execution_prohibited_in_this_stage": True,
                      "resources": None},
        "data": {"manifest_path": "data/manifests/datasets.json", "manifest_status": "missing_not_invented"},
        "project": {"output_dir": "experiments/results/executed"}}
    import yaml

    atomic_write_text(root / "experiments/configs/main.yaml", yaml.safe_dump(configuration, sort_keys=False))
    atomic_write_json(root / "experiments/RUN_SPEC.json", {
        "schema": 1, "implementation_family": "machine_learning", "protocol_id": "CSFS-v1",
        "implementation_status": "code_verified_not_executed", "execution_status": "not_executed",
        "execution_prohibited_in_this_stage": True, "run_experiment_authorized": False,
        "entrypoint": "experiments/src/train.py", "entrypoint_symbol": "main",
        "command": "python experiments/src/train.py --project . --config experiments/configs/main.yaml --allow-research-execution",
        "preflight_command": "python experiments/src/train.py --project . --config experiments/configs/main.yaml --check",
        "data": configuration["data"], "seeds": [13, 42, 73, 101, 202],
        "scientific_outputs": {"primary_metric": "macro_f1", "analysis_unit": "subject_or_declared_recording",
            "uncertainty": "five_seed_mean_within_target_then_10000_paired_dataset_bootstrap_and_signflip_Holm"},
        "code_readiness_is_not_execution_consent": True})


def _implementation_contract(root: Path, source: Path) -> None:
    """Preserve the scientific scene/claims, replace only obsolete code evidence."""
    payload = json.loads((source / "experiments/METHOD_CONTRACT.json").read_text(encoding="utf-8-sig"))
    if payload.get("schema") != 2:
        raise ValueError("The reference implementation cannot migrate an unsupported method contract")
    mappings = {
        "M1": ("data.py", ["channel_subsets", "make_batch"]),
        "M2": ("data.py", ["four_composites"]),
        "M3": ("models.py", ["CSFSModel", "FrozenLinearProbe"]),
        "M4": ("data_contract.py", ["load_data_manifest", "build_ldo_fold", "build_in_domain_fold"]),
    }
    checks = []
    for mechanism, (name, symbols) in mappings.items():
        identity = f"CSFS-V1-{mechanism}-CODE"
        checks.append({"id": identity, "description": f"Current tested {mechanism} code path; not executed research evidence.",
                       "evidence": [{"path": "experiments/src/csfs_v1/" + name, "symbols": symbols}]})
        for coverage in payload.get("mechanism_coverage") or []:
            if coverage.get("idea_mechanism_id") == mechanism:
                coverage["implementation_check_ids"] = [identity]
                coverage["status"] = "implemented"
    payload["implementation_checks"] = checks
    payload.pop("implementation_evidence_register", None)
    payload["implementation_level"] = "executable_experiment_pipeline"
    payload["code_validation_level"] = "V1_pure_local"
    payload["scientific_execution_performed"] = False
    atomic_write_json(root / "experiments/METHOD_CONTRACT.json", payload)


def _historical(relative: Path) -> bool:
    return (relative.parts[:2] == ("experiments", "src") or relative.parts[0] == ".merak"
            or relative.as_posix() in {"experiments/IMPLEMENTATION_BUILD.json", "experiments/IMPLEMENTATION_BLUEPRINT.json",
                                       "experiments/PROTOCOL_CONFORMANCE.json", "experiments/CODE_IMPLEMENTATION_ATTESTATION.json"})


def _current_negative_readiness(root: Path) -> None:
    """New tested code is not data/legal/resource readiness or scientific execution."""
    from .protocol_conformance import build_protocol_conformance_ledger

    findings = [
        {"id": "CODE-REFERENCE-IMPLEMENTED", "status": "corrected_locally", "area": "implementation",
         "declared": "Implement the frozen CSFS-v1 operational protocol without modifying numerical outcomes.",
         "observed": "Trusted source bytes and complete V1 tests verify the implemented code paths. No research data or training was executed.",
         "evidence": ["experiments/EXPERIMENT_PLAN.md", "experiments/src/csfs_v1/study.py", "experiments/RUN_SPEC.json"]},
        {"id": "DATA-AND-EXECUTION-PENDING", "status": "unvalidated", "area": "scientific_execution",
         "declared": "Legally reviewed common-endpoint data, frozen splits, environment ceilings and separate execution consent are required.",
         "observed": "No authoritative dataset manifest or resource ceilings were invented. Execution remains prohibited and C1-C3 remain unresolved.",
         "evidence": ["experiments/EXPERIMENT_PLAN.md", "experiments/configs/main.yaml", "experiments/src/csfs_v1/data_contract.py"]},
    ]
    atomic_write_json(root / "experiments/PROTOCOL_CONFORMANCE.json", build_protocol_conformance_ledger(root, findings))


def export_csfs_reference(source: Path, receipt: Path, repository: Path) -> dict:
    """Create a NEW copy; historical scientific inputs/results/traces are never overwritten."""
    from scripts.live_snapshot_resume_validation import validate_copy_boundary
    from scripts.live_snapshot_copy import safe_selected_input_files
    from scripts.verify_paper_preparation_snapshot import files
    from scripts.live_snapshot_copy import additional_input_files

    source, repository = source.resolve(strict=True), repository.resolve(strict=True)
    if source.parent != repository or source.name != "live-verification-106-bush5hv6":
        raise ValueError("Reference implementation export requires the explicitly authorized isolated source")
    validate_copy_boundary(source)
    tests, authority = _receipt(receipt, repository), _authority(source)
    science = [path for path in (source / "experiments").rglob("*") if path.is_file()
               and path.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".csv"}]
    candidates = safe_selected_input_files(source, [*files(source), *science,
                                                   *additional_input_files(source, "3de990b9ec00")])
    before = {path.relative_to(source).as_posix(): _hash(path) for path in candidates}
    destination = Path(tempfile.mkdtemp(prefix="protocol-implementation-106-", dir=repository))
    for path in candidates:
        relative = path.relative_to(source)
        target = destination / ".merak/implementation-history" / relative if _historical(relative) else destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if relative.as_posix() in {"experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", "experiments/configs/main.yaml"}:
            archive = destination / ".merak/implementation-history" / relative
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, archive)
    sources = _export_sources(destination)
    _configuration(destination)
    _implementation_contract(destination, source)
    _current_negative_readiness(destination)
    if before != {path.relative_to(source).as_posix(): _hash(path) for path in candidates}:
        raise ValueError("The source project changed during isolated implementation export")
    raw = {name: digest for name, digest in before.items() if name.endswith(".csv")}
    if any(_hash(destination / name) != digest for name, digest in raw.items()):
        raise ValueError("Reference implementation export changed frozen quantitative results")
    report = {"schema": 1, "operation": "explicit_csfs_v1_code_export", "validation_level": "V1_pure_local",
        "source_path": str(source), "project_path": str(destination), "source_sha256": sources,
        "authority": authority, "tests": tests, "raw_csv_sha256": raw,
        "source_inputs_unchanged": True, "raw_numerical_results_unchanged": True,
        "code_ready_verified": True, "scientific_execution_performed": False,
        "training_performed": False, "research_evidence": False, "experiment_authorized": False,
        "old_workflow_acceptance_reused": False, "data_and_resources_still_required": True}
    atomic_write_json(destination / "experiments/CODE_IMPLEMENTATION_ATTESTATION.json", report)
    return report
