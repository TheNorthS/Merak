"""Current table producer refresh preserves every numeric artifact and commits atomically."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from server.services import simulation_table_publication as producer
from server.services import simulation_publication_attestation as attestation
from server.services.figure_artifacts import figure_artifact_registry
from server.services.simulation_policy import SIMULATION_STABLE_IDS
from server.tests.test_simulation_publication_attestation import _bundle


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _current(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    manifest, records = _bundle(root, monkeypatch)
    payload = json.loads(manifest.read_text())
    payload.update(primary_metric="accuracy", metric_direction="maximize")
    for record, (role, identity) in zip(records, SIMULATION_STABLE_IDS.items()):
        record["id"] = identity
    # This fixture isolates publication registration, never scientific generation.
    payload["figure_files"] = records
    role_files = {"main_comparison": "main_comparison.csv", "component_ablation": "ablation.csv",
                  "training_dynamics": "training_dynamics.csv", "robustness_sensitivity": "robustness.csv",
                  "error_analysis": "error_analysis.csv", "calibration_risk_coverage": "calibration.csv",
                  "efficiency_tradeoff": "efficiency.csv"}
    payload["domain_asset_profile"] = [{
        "stable_role": role, "semantic_id": SIMULATION_STABLE_IDS[role], "data_file": filename,
        "axis_field": "component_setting" if role == "component_ablation" else "missing_channel_rate",
    } for role, filename in role_files.items()]
    payload["data_files"] = []
    for role, filename in role_files.items():
        relative = "experiments/results/simulated/" + filename
        content = ("component_setting,changed_factor,delta\n"
                   "Declared intact condition,none,+0.000\n"
                   "Without Restricted readout,registered_factor_1,-0.012\n") if role == "component_ablation" else (
            "method,score\nNamed A,0.73\nNamed B,0.68\n"
        )
        (root / relative).write_text(content, encoding="utf-8")
        payload["data_files"].append({"path": relative, "sha256": _hash((root / relative).read_bytes())})
    tables = root / "paper/tables/synthetic_preview_results.tex"
    tables.parent.mkdir(parents=True)
    table_text = "\n".join([
        r"\begin{table*}\caption{Primary comparison}\label{tab:preview-main-results}\midrule Named A & 0.73\\ Named B & 0.68\\\bottomrule\end{table*}",
        r"\begin{table*}\caption{Ablation}\label{tab:preview-ablation}\midrule" + "\n"
        + r"\textbf{none} & +0.000 \\" + "\n" + r"registered\_factor\_1 & -0.012 \\" + "\n"
        + r"\bottomrule\end{table*}",
        r"\begin{table*}\caption{Stress over missing\_channel\_rate}\label{tab:preview-robustness-calibration}\toprule missing\_channel\_rate & Score\\\midrule 0.1 & 0.6\\ 0.2 & 0.5\\\bottomrule\end{table*}",
        r"\begin{table*}\caption{Calibration}\label{tab:preview-calibration}\midrule Named A & 0.11\\ Named B & 0.14\\\bottomrule\end{table*}",
    ])
    tables.write_text(table_text, encoding="utf-8")
    payload["paper_table"] = tables.relative_to(root).as_posix()
    payload["paper_table_sha256"] = _hash(tables.read_bytes())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    registry = figure_artifact_registry.load(root / "figures")
    for entry, record in zip(registry["figures"], records):
        entry["id"] = record["id"]
        entry["metadata"]["semantic_key"] = record["id"]
        entry["metadata"]["simulation_manifest_sha256"] = _hash(manifest.read_bytes())
        role = next(role for role, identity in SIMULATION_STABLE_IDS.items() if identity == record["id"])
        relative = "experiments/results/simulated/" + role_files[role]
        entry["metadata"]["source_data"] = [relative]
        entry["metadata"]["source_data_sha256"] = {relative: _hash((root / relative).read_bytes())}
    (root / "figures/FIGURE_MANIFEST.json").write_text(json.dumps(registry), encoding="utf-8")
    return manifest


def test_prepare_publication_changes_only_labels_and_runtime_hashes(tmp_path, monkeypatch) -> None:
    manifest = _current(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    update = producer.prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    table = "paper/tables/synthetic_preview_results.tex"
    text = update.files[table].decode("utf-8")
    assert "Without Restricted readout" in text and "registered\\_factor" not in text
    assert "Missing channel rate" in text and "missing\\_channel\\_rate" not in text
    old_text = before[tmp_path / table].decode("utf-8")
    assert re.findall(r"[-+]?\d+(?:\.\d+)?", text) == re.findall(
        r"[-+]?\d+(?:\.\d+)?", old_text.replace("registered\\_factor\\_1", "Without Restricted readout")
    )
    from server.services.simulation_table_projection_binding import PUBLICATION_BINDING, verify_simulation_table_projection
    proof = json.loads(update.files[PUBLICATION_BINDING])
    assert proof["latex_sha256"] == _hash(update.files[table])
    assert proof["source_table_sha256"] == json.loads(before[manifest])["paper_table_sha256"]
    assert set(update.files) == {table, PUBLICATION_BINDING}
    assert {path: path.read_bytes() for path in before} == before
    for relative, content in update.files.items():
        (tmp_path / relative).write_bytes(content)
    assert manifest.read_bytes() == before[manifest]
    verify_simulation_table_projection(tmp_path, json.loads(manifest.read_text()))
    assert producer.prepare_simulation_table_publication(tmp_path, "objective_mechanism").files == {}


def test_table_renderer_provenance_is_stable_loaded_code_not_disk_source(monkeypatch) -> None:
    before = producer._renderer_digest()
    for _ in range(30):
        assert producer._renderer_digest() == before
    assert re.fullmatch(r"[a-f0-9]{64}", before)


def test_owner_table_registration_commits_four_exact_labels_without_changing_csvs(tmp_path, monkeypatch) -> None:
    manifest = _current(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    before = {tmp_path / item["path"]: (tmp_path / item["path"]).read_bytes() for item in payload["data_files"]}
    from server.services.paper_evidence import PaperEvidence
    from server.services.paper_submission_tables import write_submission_tables
    evidence = PaperEvidence(tmp_path, "Study", "", "", "", "", "", "",
                             asset_plan={"evidence_mode": "synthetic_preview"},
                             selected_idea={"publication": {"contribution_type": "objective_mechanism"}})
    write_submission_tables(evidence)
    table_manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text())
    assert {item["label"] for item in table_manifest["tables"]} == {
        "tab:preview-main-results", "tab:preview-ablation", "tab:preview-robustness-calibration", "tab:preview-calibration",
    }
    assert all(path.read_bytes() == content for path, content in before.items())
    first = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    write_submission_tables(evidence)
    assert all(path.read_bytes() == content for path, content in first.items())


def test_real_style_ablation_caption_uses_frozen_named_reference_and_passes_strict_policy(tmp_path, monkeypatch) -> None:
    manifest = _current(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    table = tmp_path / payload["paper_table"]
    table.write_text(table.read_text(encoding="utf-8").replace(
        r"\caption{Ablation}", r"\caption{Objective and architecture ablation. Component-removal losses relative to the full method, with uncertainty whiskers.}",
    ), encoding="utf-8")
    payload["paper_table_sha256"] = _hash(table.read_bytes())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    registry_path = tmp_path / "figures/FIGURE_MANIFEST.json"
    registry = json.loads(registry_path.read_text())
    for entry in registry["figures"]:
        entry["metadata"]["simulation_manifest_sha256"] = _hash(manifest.read_bytes())
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    before_data = {tmp_path / item["path"]: (tmp_path / item["path"]).read_bytes() for item in payload["data_files"]}
    from server.services.paper_evidence import PaperEvidence
    from server.services.paper_submission_tables import write_submission_tables
    from server.services.publication_table_policy import publication_table_issues
    evidence = PaperEvidence(tmp_path, "Study", "", "", "", "", "", "",
                             asset_plan={"evidence_mode": "synthetic_preview"},
                             selected_idea={"publication": {"contribution_type": "objective_mechanism"}})
    assert any("generic or placeholder" in issue for issue in publication_table_issues(tmp_path / "paper"))
    write_submission_tables(evidence)
    assert "relative to the Declared intact condition, with assigned scenario-bound whiskers" in table.read_text(encoding="utf-8")
    assert "not intervals estimated from repeat configurations or population samples" in table.read_text(encoding="utf-8")
    assert publication_table_issues(tmp_path / "paper") == []
    assert all(path.read_bytes() == content for path, content in before_data.items())


def test_conflicting_focal_public_method_name_cannot_be_used_to_rewrite_caption(tmp_path, monkeypatch) -> None:
    manifest = _current(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    table = tmp_path / payload["paper_table"]
    table.write_text(table.read_text(encoding="utf-8").replace(r"\caption{Ablation}", r"\caption{Relative to the full method}"), encoding="utf-8")
    payload["paper_table_sha256"] = _hash(table.read_bytes())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    ideas = tmp_path / "ideas/SELECTED_IDEA.json"
    ideas.parent.mkdir()
    ideas.write_text(json.dumps({"publication": {"method_name": "Different focal condition"}}))
    with pytest.raises(ValueError, match="conflicts with its declared public method name"):
        producer.prepare_simulation_table_publication(tmp_path, "objective_mechanism")


@pytest.mark.parametrize("defect", ["data_hash", "table_hash", "missing_label", "unsupported_layout", "schema"])
def test_invalid_source_or_layout_fails_before_preparation(tmp_path, monkeypatch, defect) -> None:
    manifest = _current(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text())
    table = tmp_path / payload["paper_table"]
    if defect == "data_hash":
        (tmp_path / payload["data_files"][0]["path"]).write_bytes(b"changed")
    elif defect == "schema":
        payload["schema"] = 10
    elif defect == "table_hash":
        table.write_bytes(b"changed")
    elif defect == "missing_label":
        table.write_text(table.read_text().replace("tab:preview-calibration", "tab:invented"))
        payload["paper_table_sha256"] = _hash(table.read_bytes())
    else:
        table.write_text(table.read_text().replace("registered\\_factor\\_1", "Unbound invented removal"))
        payload["paper_table_sha256"] = _hash(table.read_bytes())
    manifest.write_text(json.dumps(payload))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises((ValueError, OSError)):
        producer.prepare_simulation_table_publication(tmp_path, "objective_mechanism")
    assert {path: path.read_bytes() for path in before} == before
