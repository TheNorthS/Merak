"""Source discovery must see conditionally instantiated task heads."""

from __future__ import annotations

from pathlib import Path

from server.services.scientific_architecture_discovery import discover_architecture


def test_conditional_classifier_is_not_marked_contract_inferred(
    tmp_path: Path,
) -> None:
    source = tmp_path / "experiments/src/models.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class Model:\n"
        "    def __init__(self, num_classes=None):\n"
        "        self.classifier = None if num_classes is None else Linear(8, num_classes)\n"
        "    def forward(self, representation):\n"
        "        return self.classifier(representation)\n",
        encoding="utf-8",
    )
    method = {
        "evaluation_contract": {"primary_outcomes": ["Accuracy"]},
        "implementation_checks": [],
    }

    architecture = discover_architecture(tmp_path, method)

    assert not architecture["completeness_issues"]
    assert any(
        item.get("source_symbol") == "Model.classifier"
        for item in architecture["components"]
    )
    assert not any(
        item.get("evidence_status") == "contract_inferred"
        for item in architecture["components"]
    )


def test_camel_case_task_head_class_is_detected_without_a_classifier_named_attribute(tmp_path):
    source = tmp_path / "experiments/src/models.py"
    source.parent.mkdir(parents=True)
    source.write_text("class TaskHead(nn.Module):\n"
        "    def __init__(self):\n        self.heads = nn.ModuleDict()\n"
        "    def forward(self, representation, task):\n        return self.heads[task](representation)\n")
    architecture = discover_architecture(tmp_path, {
        "evaluation_contract":{"primary_outcomes":["Accuracy"]}, "implementation_checks":[]})
    assert not architecture["completeness_issues"]
    assert any(item.get("source_symbol") == "TaskHead" for item in architecture["components"])
    assert not any(item.get("evidence_status") == "contract_inferred" for item in architecture["components"])
