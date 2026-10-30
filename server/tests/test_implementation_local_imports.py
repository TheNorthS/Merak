"""Called lazy imports are evidence only in their precise invoked lexical scope."""

import ast
from pathlib import Path

import pytest

from server.services.implementation_graph import reachable_graph, reachable_nodes_source


def _graph(source, additional=None):
    sources = {"pkg/train.py": source, "pkg/models.py": "class Network:\n    def forward(self,x):\n        return local_scientific_forward(x)\n"}
    sources.update(additional or {})
    return reachable_graph({Path(name): ast.parse(code) for name, code in sources.items()}, Path("pkg/train.py"))


@pytest.mark.parametrize("declaration,call", [
    ("from .models import Network", "Network()"),
    ("from pkg.models import Network as Encoder", "Encoder()"),
    ("from . import models", "models.Network()"),
    ("import pkg.models as architecture", "architecture.Network()"),
])
def test_called_local_symbol_or_package_import_reaches_actual_scientific_class(declaration, call):
    calls, nodes = _graph(f"def main():\n    {declaration}\n    return {call}\n")
    assert "local_scientific_forward" in calls
    assert "class Network" in reachable_nodes_source(nodes)


@pytest.mark.parametrize("source", [
    "def unused():\n    from .models import Network\ndef main():\n    return Network()\n",
    "def main():\n    def unused():\n        from .models import Network\n        return Network()\n    return 1\n",
    "def main():\n    def first():\n        from .models import Network\n        return 1\n    def second():\n        return Network()\n    first()\n    return second()\n",
    "def first():\n    from .models import Network\n    return 1\ndef main():\n    first()\n    return Network()\n",
])
def test_uncalled_nested_or_foreign_lexical_import_cannot_pollute_call_site(source):
    _calls, nodes = _graph(source)
    assert "class Network" not in reachable_nodes_source(nodes)


@pytest.mark.parametrize("source", [
    "from .models import Network\ndef main(Network):\n    return Network()\n",
    "from .models import Network\ndef main():\n    Network = external_factory\n    return Network()\n",
    "def main():\n    from .models import Network\n    Network = external_factory\n    return Network()\n",
    "from .models import Network\ndef main():\n    def Network():\n        return 1\n    return Network()\n",
    "from .models import Network\ndef main():\n    def inner(Network):\n        return Network()\n    return inner(external_factory)\n",
    "def main():\n    import pkg.models as architecture\n    architecture = foreign_module\n    return architecture.Network()\n",
])
def test_shadowed_alias_or_parameter_never_resolves_to_uninvoked_local_evidence(source):
    _calls, nodes = _graph(source)
    assert "class Network" not in reachable_nodes_source(nodes)


def test_called_closure_can_inherit_its_enclosing_local_import_but_not_sibling_imports():
    calls, nodes = _graph("def main():\n    from .models import Network\n    def nested():\n        return Network()\n    return nested()\n")
    assert "local_scientific_forward" in calls and "class Network" in reachable_nodes_source(nodes)


def test_called_nested_scope_can_bind_its_own_local_import():
    calls, nodes = _graph("def main():\n    def nested():\n        from .models import Network\n        return Network()\n    return nested()\n")
    assert "local_scientific_forward" in calls and "class Network" in reachable_nodes_source(nodes)


def test_outer_parameter_shadowing_does_not_escape_via_nested_same_named_module_definition():
    source = ("def Network():\n    return false_global_scientific_body()\n"
              "def main(Network):\n    def nested():\n        return Network()\n    return nested()\n")
    calls, nodes = _graph(source)
    assert "false_global_scientific_body" not in calls
    assert "false_global_scientific_body" not in reachable_nodes_source(nodes)


def test_called_child_local_import_legitimately_rebinds_outer_parameter_without_global_leak():
    source = ("def main(Network):\n    def nested():\n        from .models import Network\n"
              "        return Network()\n    return nested()\n")
    calls, nodes = _graph(source)
    assert "local_scientific_forward" in calls and "class Network" in reachable_nodes_source(nodes)


def test_function_guarded_equivalent_relative_imports_are_supported_but_conflicts_are_not():
    source = "def main():\n    try:\n        from pkg.models import Network\n    except ImportError:\n        from .models import Network\n    return Network()\n"
    assert "class Network" in reachable_nodes_source(_graph(source)[1])
    conflict = source.replace("from .models import Network", "from other import Foreign as Network")
    nodes = _graph(conflict, {"other.py": "class Foreign:\n    pass\n"})[1]
    assert "class Network" not in reachable_nodes_source(nodes) and "class Foreign" not in reachable_nodes_source(nodes)


def test_local_imports_respect_multilevel_package_and_do_not_pick_same_stem_foreign_module():
    sources = {"pkg/train.py": "from .inner.cli import main\nif __name__=='__main__':\n    main()\n",
               "pkg/inner/cli.py": "def main():\n    from ..models import Network\n    return Network()\n",
               "pkg/models.py": "class Network:\n    def forward(self,x):\n        return true_owned_forward(x)\n",
               "other/models.py": "class Network:\n    def forward(self,x):\n        return foreign_fake_forward(x)\n"}
    calls, _nodes = reachable_graph({Path(name): ast.parse(code) for name, code in sources.items()}, Path("pkg/train.py"))
    assert "true_owned_forward" in calls and "foreign_fake_forward" not in calls


def test_real_trusted_csfs_lazy_entrypoint_graph_is_readonly_ast_and_has_all_actual_scientific_flows(tmp_path, monkeypatch):
    from server.services.experiment_implementation import experiment_implementation_service

    source = Path(__file__).resolve().parents[1] / "experiment_protocols/csfs_v1"
    trees = {Path("experiments/src/csfs_v1") / path.name: ast.parse(path.read_text(encoding="utf-8-sig"))
             for path in source.glob("*.py")}
    entry = Path("experiments/src/train.py")
    trees[entry] = ast.parse("from csfs_v1.cli import main\nif __name__=='__main__':\n    main()\n")
    before = {path: ast.dump(tree, include_attributes=True) for path, tree in trees.items()}
    calls, nodes = reachable_graph(trees, entry)
    capabilities = experiment_implementation_service._source_capabilities(reachable_nodes_source(nodes))
    assert all(capabilities.values()), capabilities
    assert {"run_study", "load_data_manifest", "make_batch", "channel_subsets", "four_composites",
            "CSFSModel", "FrozenLinearProbe", "_finite_update", "evaluate_frozen_probe"} <= calls
    assert {path: ast.dump(tree, include_attributes=True) for path, tree in trees.items()} == before
