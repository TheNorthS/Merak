"""Pure AST regressions for project-local guarded import reachability."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.services.implementation_graph import reachable_graph, reachable_nodes_source


def _graph(sources: dict[str, str], entrypoint: str = "train.py"):
    trees = {Path(name): ast.parse(source) for name, source in sources.items()}
    return reachable_graph(trees, Path(entrypoint))


def _classes(nodes: list[ast.AST]) -> set[str]:
    return {node.name for node in nodes if isinstance(node, ast.ClassDef)}


_MODEL = """
class CSMTNCModel:
    def __init__(self, masker=None):
        self.masker = masker
        self.classifier = Linear(32, 2)

    def forward(self, batch, **kwargs):
        return {"logits": self.classifier(batch)}

class ChannelSetMasker:
    def forward(self, batch):
        return batch
"""


def test_guarded_absolute_relative_imports_reach_real_training_model() -> None:
    calls, nodes = _graph({
        "experiments/src/train.py": """
try:
    from data import build_fold_dataloaders
    from models import CSMTNCModel, ChannelSetMasker
    from objectives import CSMTNCObjective
except ImportError:
    from .data import build_fold_dataloaders
    from .models import CSMTNCModel, ChannelSetMasker
    from .objectives import CSMTNCObjective

def train_fold_condition():
    model = CSMTNCModel(masker=ChannelSetMasker())
    objective = CSMTNCObjective()
    for batch in build_fold_dataloaders():
        outputs = model(batch, channel_set_aware_masking=True)
        terms = objective(outputs, batch)
    return terms

def run_training():
    return train_fold_condition()

def main():
    return run_training()
""",
        "experiments/src/models.py": _MODEL,
        "experiments/src/data.py": "def build_fold_dataloaders():\n    return DataLoader(Dataset())\n",
        "experiments/src/objectives.py": "class CSMTNCObjective:\n    def forward(self, outputs, batch):\n        return cross_entropy(outputs['logits'], batch)\n",
    }, "experiments/src/train.py")

    assert {"CSMTNCModel", "ChannelSetMasker", "CSMTNCObjective"} <= _classes(nodes)
    assert "build_fold_dataloaders" in calls
    assert "classifier" in "\n".join(ast.unparse(node) for node in nodes)


@pytest.mark.parametrize("guard", [
    "if USE_LOCAL:\n{body}",
    "with import_context():\n{body}",
    "for configuration in configurations:\n{body}",
    "while resolving:\n{body}",
    "try:\n{body}\nexcept ImportError:\n    import external_dependency",
    "try:\n    import external_dependency\nexcept ImportError:\n{body}",
    "try:\n    import external_dependency\nfinally:\n{body}",
])
def test_module_lexical_guards_do_not_hide_local_imports(guard: str) -> None:
    imports = guard.format(body="    from models import CSMTNCModel")
    _, nodes = _graph({
        "train.py": imports + "\n\ndef main():\n    return CSMTNCModel()\n",
        "models.py": _MODEL,
    })
    assert "CSMTNCModel" in _classes(nodes)


@pytest.mark.parametrize("source", [
    "try:\n    from models import CSMTNCModel\nexcept ImportError:\n    from .models import CSMTNCModel\ndef main():\n    return 1\n",
    "def unused_factory():\n    from models import CSMTNCModel\n    return CSMTNCModel()\ndef main():\n    return 1\n",
    "class UnusedFactory:\n    from models import CSMTNCModel\n    def create(self):\n        return self.CSMTNCModel()\ndef main():\n    return 1\n",
    "def unused_factory():\n    from models import CSMTNCModel\ndef main():\n    return CSMTNCModel()\n",
])
def test_unused_or_inner_scope_imports_do_not_reach_model(source: str) -> None:
    _, nodes = _graph({"train.py": source, "models.py": _MODEL})
    assert "CSMTNCModel" not in _classes(nodes)


def test_called_function_does_not_reach_uncalled_nested_factory() -> None:
    _, nodes = _graph({
        "train.py": """
from models import CSMTNCModel
def main():
    def unused_factory():
        return CSMTNCModel()
    return 1
""",
        "models.py": _MODEL,
    })
    assert "CSMTNCModel" not in _classes(nodes)


@pytest.mark.parametrize("imports,call", [
    ("import package.models as architecture", "architecture.CSMTNCModel()"),
    ("import package.models", "package.models.CSMTNCModel()"),
    ("from package import models", "models.CSMTNCModel()"),
    ("from . import models", "models.CSMTNCModel()"),
    ("from package.models import CSMTNCModel as Network", "Network()"),
])
def test_module_and_symbol_aliases_resolve_project_paths(imports: str, call: str) -> None:
    _, nodes = _graph({
        "package/train.py": imports + f"\ndef main():\n    return {call}\n",
        "package/models.py": _MODEL,
    }, "package/train.py")
    assert "CSMTNCModel" in _classes(nodes)


def test_relative_import_uses_its_package_not_same_named_other_module() -> None:
    _, nodes = _graph({
        "alpha/train.py": "from .models import CSMTNCModel\ndef main():\n    return CSMTNCModel()\n",
        "alpha/models.py": _MODEL,
        "beta/models.py": "class WrongModel:\n    def forward(self, x):\n        return x\n",
    }, "alpha/train.py")
    assert "CSMTNCModel" in _classes(nodes)
    assert "WrongModel" not in _classes(nodes)


def test_symbol_definition_takes_precedence_over_same_named_module() -> None:
    _, nodes = _graph({
        "train.py": "from models import CSMTNCModel\ndef main():\n    return CSMTNCModel()\n",
        "models.py": _MODEL,
        "CSMTNCModel.py": "class WrongModel:\n    def forward(self, x):\n        return x\n",
    })
    assert "CSMTNCModel" in _classes(nodes)
    assert "WrongModel" not in _classes(nodes)


def test_conflicting_guarded_aliases_cannot_choose_arbitrary_evidence() -> None:
    _, nodes = _graph({
        "train.py": """
if MODE:
    from alpha.models import CSMTNCModel as Network
else:
    from beta.models import OtherModel as Network
def main():
    return Network()
""",
        "alpha/models.py": _MODEL,
        "beta/models.py": "class OtherModel:\n    def forward(self, x):\n        return x\n",
    })
    assert not _classes(nodes)


def test_same_package_module_imports_keep_independent_qualified_bindings() -> None:
    calls, nodes = _graph({
        "train.py": """
import package.models
import package.objectives
def main():
    model = package.models.CSMTNCModel()
    return package.objectives.loss(model)
""",
        "package/models.py": _MODEL,
        "package/objectives.py": "def loss(model):\n    return cross_entropy(model)\n",
    })
    assert "CSMTNCModel" in _classes(nodes)
    assert "cross_entropy" in calls


def test_ambiguous_same_stem_outside_package_cannot_resolve_by_order() -> None:
    _, nodes = _graph({
        "train.py": "from models import CSMTNCModel\ndef main():\n    return CSMTNCModel()\n",
        "alpha/models.py": _MODEL,
        "beta/models.py": _MODEL,
    })
    assert not _classes(nodes)


def test_called_nested_helper_preserves_external_import_reachability() -> None:
    calls, nodes = _graph({
        "train.py": """
from models import CSMTNCModel
def main():
    def build():
        return CSMTNCModel()
    return build()
""",
        "models.py": _MODEL,
    })
    assert "CSMTNCModel" in _classes(nodes)
    assert "build" in calls


def test_source_projection_omits_uncalled_nested_head_and_optimizer() -> None:
    _, nodes = _graph({"train.py": """
def main():
    def unused_classifier():
        logits = classifier(batch)
        loss.backward()
        optimizer.step()
        return logits
    classification_head = lambda batch: predictor(batch)
    return 1
"""})
    before = [ast.dump(node, include_attributes=True) for node in nodes]
    source = reachable_nodes_source(nodes)
    assert "classifier" not in source
    assert "classification_head" not in source
    assert "predictor" not in source
    assert "backward" not in source
    assert "optimizer" not in source
    assert [ast.dump(node, include_attributes=True) for node in nodes] == before


def test_source_projection_does_not_treat_unused_guarded_head_import_as_inference() -> None:
    _, nodes = _graph({
        "train.py": """
try:
    from heads import ClassifierHead
except ImportError:
    from .heads import ClassifierHead
def main():
    return 1
""",
        "heads.py": "class ClassifierHead:\n    def forward(self, value):\n        return value\n",
    })
    assert "ClassifierHead" not in reachable_nodes_source(nodes)


def test_source_projection_recognizes_transitively_called_nested_helpers() -> None:
    _, nodes = _graph({"train.py": """
def main():
    def output(batch):
        return head(batch)
    def head(batch):
        logits = classifier(batch)
        return logits
    def unused(batch):
        return fake_classifier(batch)
    return output(batch)
"""})
    source = reachable_nodes_source(nodes)
    assert "logits = classifier(batch)" in source
    assert "fake_classifier" not in source


@pytest.mark.parametrize("operation", [
    "return head(batch)",
    "return map(head, batches)",
])
def test_source_projection_recognizes_called_or_passed_local_lambda(operation: str) -> None:
    _, nodes = _graph({"train.py": (
        "def main():\n"
        "    head = lambda batch: classifier(batch)\n"
        f"    {operation}\n"
    )})
    assert "classifier(batch)" in reachable_nodes_source(nodes)


def test_source_projection_keeps_framework_callbacks_but_prunes_dead_inner_helper() -> None:
    _, nodes = _graph({"train.py": """
class Model:
    def forward(self, batch):
        def unused():
            return fake_classifier(batch)
        return self.classifier(batch)
def main():
    return Model()
"""})
    source = reachable_nodes_source(nodes)
    assert "def forward" in source
    assert "self.classifier(batch)" in source
    assert "fake_classifier" not in source
