"""Local artifact audits must not accept evidence from uninvoked inner scopes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.experiment_implementation import experiment_implementation_service


def _write_pipeline(root: Path, source: str) -> None:
    directory = root / "experiments"
    (directory / "src").mkdir(parents=True)
    (directory / "src" / "train.py").write_text(source, encoding="utf-8")
    (directory / "RUN_SPEC.json").write_text(json.dumps({
        "entrypoint": "experiments/src/train.py",
        "command": "python experiments/src/train.py",
    }), encoding="utf-8")
    (directory / "METHOD_CONTRACT.json").write_text(json.dumps({
        "schema": 2,
        "status": "implemented",
        "implementation_level": "executable_training_pipeline",
        "evaluation_contract": {"primary_outcomes": ["accuracy"]},
    }), encoding="utf-8")


def _pipeline(*, helper: str = "", head: str = "embeddings", optimize: str = "loss.backward(); optimizer.step()") -> str:
    return f"""
import json
class Model:
    def forward(self, batch):
        return batch
def main():
{helper}
    model = Model()
    optimizer = Adam(model.parameters())
    for batch in DataLoader(Dataset()):
        embeddings = model.forward(batch)
        predictions = {head}
        loss = mse_loss(predictions, batch)
        {optimize}
    model.eval()
    metrics = {{"accuracy": accuracy(predictions, batch)}}
    json.dump(metrics, open("metrics.json", "w"))
    return metrics
"""


@pytest.mark.parametrize("helper", [
    "    def unused():\n        logits = classifier(batch)\n        return logits",
    "    classification_head = lambda batch: predictor(batch)",
])
def test_unused_inner_head_cannot_satisfy_inference_gate(tmp_path: Path, helper: str) -> None:
    _write_pipeline(tmp_path, _pipeline(helper=helper))
    report = experiment_implementation_service.audit(tmp_path)
    ids = {finding["id"] for finding in report["findings"]}
    assert "IMPL-INFERENCE-001" in ids


def test_unused_guarded_head_import_cannot_satisfy_inference_gate(tmp_path: Path) -> None:
    source = "try:\n    from heads import ClassifierHead\nexcept ImportError:\n    from .heads import ClassifierHead\n"
    _write_pipeline(tmp_path, source + _pipeline())
    (tmp_path / "experiments/src/heads.py").write_text(
        "class ClassifierHead:\n    def forward(self, x):\n        return x\n",
        encoding="utf-8",
    )
    report = experiment_implementation_service.audit(tmp_path)
    assert any(finding["id"] == "IMPL-INFERENCE-001" for finding in report["findings"])


def test_unused_inner_optimizer_cannot_satisfy_optimization_gate(tmp_path: Path) -> None:
    helper = "    def unused():\n        loss.backward()\n        optimizer.step()"
    _write_pipeline(tmp_path, _pipeline(helper=helper, head="classifier(embeddings)", optimize="store(loss)"))
    report = experiment_implementation_service.audit(tmp_path)
    ids = {finding["id"] for finding in report["findings"]}
    assert "IMPL-FLOW-OPTIMIZATION" in ids


def test_called_inner_prediction_head_remains_valid_evidence(tmp_path: Path) -> None:
    helper = "    def compute_prediction(batch):\n        logits = classifier(batch)\n        return logits"
    _write_pipeline(tmp_path, _pipeline(helper=helper, head="compute_prediction(embeddings)"))
    report = experiment_implementation_service.audit(tmp_path)
    assert report["verdict"] == "PASS", report["findings"]


def test_called_inner_optimizer_remains_valid_evidence(tmp_path: Path) -> None:
    helper = "    def update(loss):\n        loss.backward()\n        optimizer.step()"
    _write_pipeline(tmp_path, _pipeline(helper=helper, head="classifier(embeddings)", optimize="update(loss)"))
    report = experiment_implementation_service.audit(tmp_path)
    assert report["verdict"] == "PASS", report["findings"]
