"""Exercise artifact contracts with an isolated test renderer, not experiments."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import pytest

from server.services.experiment_placeholders import ExperimentPlaceholderService
from server.services.simulation_ranking_evidence import RankingEvidence, paired_ranking_rows
from server.tests._planned_publication_fixture import author_publication_fixture


def test_paired_interval_uses_the_declared_seed_critical_value() -> None:
    evidence = RankingEvidence(
        [("Reference", "reference"), ("Candidate", "candidate")],
        {("reference", "iid_accuracy"): [0.6, 0.61],
         ("candidate", "iid_accuracy"): [0.62, 0.64]}, [],
    )
    axes = [{"axis_id": "iid_accuracy", "metric_key": "accuracy",
             "direction": "maximize", "mpid": 0.01}]
    def simulate(row: dict) -> dict[str, str]:
        return {key: str(value) for key, value in row.items()}
    rows = paired_ranking_rows(
        evidence, axes, [13, 42], 0.05, lambda _: True, simulate,
        critical_value=12.706,
    )
    expected_width = 12.706 * 0.005
    assert float(rows[0]["paired_ci_low"]) == pytest.approx(0.025 - expected_width)
    assert float(rows[0]["paired_ci_high"]) == pytest.approx(0.025 + expected_width)
    assert rows[0]["in_holm_family"] == "false"


@pytest.mark.parametrize("seeds", [[13, 42], [13, 42, 73, 101, 202]])
def test_benchmark_stages_preserve_models_seeds_and_hash_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seeds: list[int],
) -> None:
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "status": "accepted", "title": "Registered generic comparison",
        "claims": [{"id": "C1", "statement": "Rankings may vary across axes",
                    "measurable_endpoints": ["paired effects", "reversal flags"]}],
        "mechanisms": [{"id": "M1", "name": "Registered representation"}],
    }), encoding="utf-8")
    config_dir = tmp_path / "experiments" / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "main.yaml").write_text(
        "experiment:\n  primary_metric: accuracy\n"
        "method:\n  model_suite: [linear_reference, mlp_reference]\n"
        "  ranking_registry:\n    axes:\n"
        "      - {axis_id: iid_accuracy, metric_key: accuracy, direction: maximize, mpid: 0.01}\n"
        "      - {axis_id: shifted_nll, metric_key: shifted_nll, direction: minimize, mpid: 0.01}\n"
        "execution:\n  max_epochs: 10\n",
        encoding="utf-8",
    )
    (config_dir.parent / "RUN_SPEC.json").write_text(
        json.dumps({"seeds": seeds}), encoding="utf-8",
    )
    author_publication_fixture(tmp_path, method_name="Registered generic comparison",
                               comparators=["Linear Reference", "Mlp Reference"])

    async def isolated_renderer(script: Path) -> tuple[bool, str]:
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
        # These bytes are fixture products, never evaluated as visual quality.
        for suffix in (".pdf", ".svg", ".png"):
            script.with_suffix(suffix).write_bytes(b"isolated renderer boundary fixture")
        return True, ""

    service = ExperimentPlaceholderService()
    monkeypatch.setattr(service, "_render", isolated_renderer)
    plan = asyncio.run(service.ensure(tmp_path, evidence_mode="synthetic_preview"))
    manifest_path = tmp_path / plan["simulation_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert plan["simulation_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest["replicate_contract"]["seed_ids"] == seeds
    assert manifest["registered_pair_contract"]["observed_comparison_count"] == 2
    assert manifest["registered_pair_contract"]["holm_family_size"] == 1
    assert manifest["evidence_package"]["provenance_join_contract"]["coverage"] == 1.0
    assert len(manifest["figure_files"]) == 7
    for item in manifest["data_files"]:
        assert hashlib.sha256((tmp_path / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    with (tmp_path / "experiments/results/simulated/run_level_results.csv").open(
        encoding="utf-8-sig", newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert {int(row["seed"]) for row in rows} == set(seeds)
    assert len(plan["figures"]) == 7
