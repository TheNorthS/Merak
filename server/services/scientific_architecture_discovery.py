"""Static, source-bound discovery of scientific implementation architecture."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .method_contract import (
    implementation_evidence_register_map,
    normalize_implementation_evidence,
    resolve_implementation_evidence,
)


def discover_architecture(root: Path, method: dict[str, Any]) -> dict[str, Any]:
    discovery = ArchitectureDiscovery(root, method)
    discovery.scan_evidence_register()
    discovery.load_architecture_modules()
    discovery.discover_predictive_heads()
    discovery.discover_neural_modules()
    components, flows = discovery.resolve_aliases()
    from .scientific_architecture_projection import project_architecture

    return project_architecture(
        root=root, implementation_family=discovery.family, method=method,
        components=components, flows=flows,
        source_paths=discovery.source_paths,
        constraints=discovery.configuration_constraints,
        verification_symbols=discovery.verification_symbols,
    )


class ArchitectureDiscovery:
    def __init__(self, root: Path, method: dict[str, Any]) -> None:
        from .scientific_assets import _contract_json

        self.root = root
        self.method = method
        blueprint = _contract_json(root / "experiments" / "IMPLEMENTATION_BLUEPRINT.json")
        self.family = str(
            blueprint.get("implementation_family")
            or method.get("implementation_family") or "computational_general"
        ).strip().casefold()
        self.components: list[dict[str, Any]] = []
        self.flows: list[dict[str, str]] = []
        self.source_paths: list[str] = []
        self.configuration_constraints: list[dict[str, str]] = []
        self.verification_symbols: list[dict[str, str]] = []
        self.parsed_modules: dict[Path, ast.Module] = {}
        self.architecture_modules: dict[Path, ast.Module] = {}
        self.component_ids: dict[tuple[str, str], str] = {}
        self.class_forward_sequences: dict[str, list[str]] = {}
        self.inspected_classes: set[tuple[Path, str]] = set()

    def add_component(
        self, *, label: str, source_path: str, source_symbol: str,
        operation: str, parent: str = "",
    ) -> str:
        from .scientific_assets import _clean_name

        key = (source_path, source_symbol)
        if key in self.component_ids:
            return self.component_ids[key]
        base = _clean_id(f"{source_symbol}_{label}") or f"component_{len(self.components) + 1}"
        component_id = _unique_component_id(self.components, base)
        visible = not _is_plumbing_symbol(source_symbol)
        self.components.append({
            "id": component_id,
            "label": _clean_name(label, source_symbol, 100),
            "display_name": _publication_name(label or source_symbol),
            "operation": _clean_name(operation, "Declared implementation component", 240),
            "lane": _lane_for(self.family, label, source_path, source_symbol, operation),
            "source_path": source_path, "source_symbol": source_symbol,
            "parent_component": parent, "required_visual": visible,
            "publication_visible": visible,
        })
        self.component_ids[key] = component_id
        return component_id

    def scan_evidence_register(self) -> None:
        register = implementation_evidence_register_map(self.method)
        for check in self.method.get("implementation_checks") or []:
            if not isinstance(check, dict):
                continue
            description = _check_description(check)
            check_id = str(check.get("id") or check.get("check_id") or "").strip()
            value = resolve_implementation_evidence(check, register.get(check_id))
            for evidence in normalize_implementation_evidence(value):
                if isinstance(evidence, dict):
                    self._scan_evidence(evidence, description)

    def _scan_evidence(self, evidence: dict[str, Any], description: str) -> None:
        relative = str(evidence.get("path") or "").strip().replace("\\", "/")
        candidate = (self.root / relative).resolve() if relative else self.root
        if not _safe_source(self.root, candidate):
            return
        if relative not in self.source_paths:
            self.source_paths.append(relative)
        self.configuration_constraints.extend({
            "key": str(value).strip(), "source_path": relative,
            "purpose": description,
        } for value in evidence.get("config_keys") or [] if str(value).strip())
        module = self._parsed_module(candidate)
        for symbol in [str(value).strip() for value in evidence.get("symbols") or []
                       if str(value).strip()]:
            if _verification_symbol(candidate, symbol):
                self.verification_symbols.append({
                    "source_path": relative, "source_symbol": symbol,
                    "purpose": description,
                })
                continue
            self.add_component(
                label=symbol.rsplit(".", 1)[-1], source_path=relative,
                source_symbol=symbol, operation=description,
            )
            self._inspect_named_class(candidate, relative, module, symbol, description)

    def _parsed_module(self, candidate: Path) -> ast.Module | None:
        if candidate.suffix.casefold() != ".py":
            return None
        if candidate not in self.parsed_modules:
            try:
                self.parsed_modules[candidate] = ast.parse(
                    candidate.read_text(encoding="utf-8-sig", errors="replace")
                )
            except (OSError, SyntaxError, UnicodeError):
                return None
        return self.parsed_modules.get(candidate)

    def _inspect_named_class(
        self, candidate: Path, relative: str, module: ast.Module | None,
        symbol: str, description: str,
    ) -> None:
        class_name = symbol.split(".", 1)[0]
        class_node = next((
            item for item in (module.body if module else [])
            if isinstance(item, ast.ClassDef) and item.name == class_name
        ), None)
        key = (candidate, class_name)
        if class_node is None or key in self.inspected_classes:
            return
        self.inspected_classes.add(key)
        parent = self.add_component(
            label=class_name, source_path=relative,
            source_symbol=class_name, operation=description,
        )
        children = self._class_init_components(class_node, relative, parent)
        self._class_forward_flow(class_node, relative, parent)
        self.flows.extend({
            "from": parent, "to": child, "operation": "contains",
            "flow_kind": "containment", "source_path": relative,
            "source_symbol": class_name,
        } for child in children)

    def _class_init_components(
        self, class_node: ast.ClassDef, relative: str, parent: str
    ) -> list[str]:
        init = _class_method(class_node, "__init__")
        if init is None:
            return []
        children = []
        for node in ast.walk(init):
            assignment = _self_assignment(node)
            if assignment is None:
                continue
            attribute, value = assignment
            children.append(self.add_component(
                label=attribute.replace("_", " ").title(),
                source_path=relative,
                source_symbol=f"{class_node.name}.{attribute}",
                operation=_unparse(value, attribute), parent=parent,
            ))
        return children

    def _class_forward_flow(
        self, class_node: ast.ClassDef, relative: str, parent: str
    ) -> None:
        forward = _class_method(class_node, "forward")
        if forward is None:
            return
        attributes = {
            str(item.get("source_symbol") or "").rsplit(".", 1)[-1]: str(item.get("id") or "")
            for item in self.components
            if item.get("source_path") == relative
            and str(item.get("source_symbol") or "").startswith(f"{class_node.name}.")
        }
        sequence = forward_module_sequence(forward, attributes)
        self.class_forward_sequences[parent] = [item for item, _ in sequence]
        for (source, _), (target, operation) in zip(sequence, sequence[1:]):
            self.flows.append({
                "from": source, "to": target, "operation": operation,
                "flow_kind": "data", "source_path": relative,
                "source_symbol": f"{class_node.name}.forward",
            })

    def load_architecture_modules(self) -> None:
        self.architecture_modules = dict(self.parsed_modules)
        for filename in (
            "models.py", "model.py", "network.py", "networks.py",
            "architecture.py", "architectures.py",
        ):
            candidate = (self.root / "experiments" / "src" / filename).resolve()
            if candidate not in self.architecture_modules and candidate.is_file():
                module = self._parsed_module(candidate)
                if module is not None:
                    self.architecture_modules[candidate] = module
                    relative = candidate.relative_to(self.root).as_posix()
                    if relative not in self.source_paths:
                        self.source_paths.append(relative)

    def discover_predictive_heads(self) -> None:
        pattern = re.compile(
            r"(?:^|_)(?:classifier|classification_head|task_head|prediction_head|predictor|logits?)(?:$|_)",
            re.IGNORECASE,
        )
        for candidate, module in self.architecture_modules.items():
            relative = _relative(self.root, candidate)
            if not relative:
                continue
            for class_node in (item for item in module.body if isinstance(item, ast.ClassDef)):
                init = _class_method(class_node, "__init__")
                for node in ast.walk(init) if init is not None else []:
                    assignment = _self_assignment(node)
                    if assignment is not None and pattern.search(assignment[0]):
                        self._add_predictive_head(relative, class_node, *assignment)

    def _add_predictive_head(
        self, relative: str, class_node: ast.ClassDef,
        attribute: str, value: ast.AST,
    ) -> None:
        class_id = self.add_component(
            label=class_node.name, source_path=relative,
            source_symbol=class_node.name, operation="Implemented predictive model",
        )
        head_id = self.add_component(
            label=attribute.replace("_", " ").title(), source_path=relative,
            source_symbol=f"{class_node.name}.{attribute}",
            operation=_unparse(value, attribute), parent=class_id,
        )
        for item in self.components:
            if item.get("id") == class_id:
                item["lane"] = "representation_model"
            elif item.get("id") == head_id:
                item["lane"] = "evaluation"
        self.flows.append({
            "from": class_id, "to": head_id,
            "operation": "contains predictive head", "flow_kind": "containment",
            "source_path": relative, "source_symbol": class_node.name,
        })

    def discover_neural_modules(self) -> None:
        architecture_names = {
            "models.py", "model.py", "network.py", "networks.py",
            "architecture.py", "architectures.py",
        }
        for candidate, module in self.architecture_modules.items():
            if candidate.name.casefold() not in architecture_names:
                continue
            relative = _relative(self.root, candidate)
            for class_node in (item for item in module.body if isinstance(item, ast.ClassDef)):
                bases = " ".join(_unparse(base, "") for base in class_node.bases)
                if "module" not in bases.casefold():
                    continue
                operations = _class_module_operations(class_node)
                forward = _class_method(class_node, "forward")
                skip = bool(forward and any(
                    isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add)
                    for item in ast.walk(forward)
                ))
                operation = " → ".join(operations[:6]) or "Predictive neural module"
                if skip:
                    operation += " with skip connection"
                component_id = self.add_component(
                    label=class_node.name, source_path=relative,
                    source_symbol=class_node.name, operation=operation,
                )
                next(item for item in self.components if item["id"] == component_id)["lane"] = "representation_model"

    def resolve_aliases(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        classes = {
            (_relative(self.root, path), item.name)
            for path, module in self.architecture_modules.items()
            for item in module.body if isinstance(item, ast.ClassDef)
        }
        class_ids = {
            (str(item.get("source_path") or ""), str(item.get("source_symbol") or "")): str(item.get("id") or "")
            for item in self.components
            if (str(item.get("source_path") or ""), str(item.get("source_symbol") or "")) in classes
        }
        aliases = _alias_targets(self.components, class_ids)

        def resolve(component_id: str, boundary: str = "") -> str:
            target = aliases.get(component_id, component_id)
            if not boundary:
                return target
            sequence = self.class_forward_sequences.get(target) or []
            boundary_id = (sequence[0] if boundary == "input" else sequence[-1]) if sequence else target
            return resolve(boundary_id, boundary) if boundary_id in aliases and boundary_id != component_id else boundary_id

        components = [item for item in self.components if item.get("id") not in aliases]
        for item in components:
            if item.get("parent_component"):
                item["parent_component"] = resolve(str(item["parent_component"]))
        flows = _resolve_flows(self.flows, aliases, resolve)
        return components, flows


def forward_module_sequence(
    forward: ast.FunctionDef | ast.AsyncFunctionDef,
    attribute_ids: dict[str, str],
) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    _scan_statements(forward.body, {}, attribute_ids, sequence)
    return sequence


def _scan_statements(
    body: list[ast.stmt], loop_variables: dict[str, str],
    attribute_ids: dict[str, str], sequence: list[tuple[str, str]],
) -> None:
    for statement in body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            _scan_expression(statement.value, loop_variables, attribute_ids, sequence)
        elif isinstance(statement, (ast.Return, ast.Expr, ast.Raise)):
            _scan_expression(getattr(statement, "value", None), loop_variables, attribute_ids, sequence)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            local = dict(loop_variables)
            if (isinstance(statement.target, ast.Name) and isinstance(statement.iter, ast.Attribute)
                    and isinstance(statement.iter.value, ast.Name) and statement.iter.value.id == "self"):
                component_id = attribute_ids.get(statement.iter.attr, "")
                if component_id:
                    local[statement.target.id] = component_id
            _scan_expression(statement.iter, loop_variables, attribute_ids, sequence)
            _scan_statements(statement.body, local, attribute_ids, sequence)
            _scan_statements(statement.orelse, loop_variables, attribute_ids, sequence)
        elif isinstance(statement, ast.If):
            _scan_expression(statement.test, loop_variables, attribute_ids, sequence)
            _scan_statements(statement.body, dict(loop_variables), attribute_ids, sequence)
            _scan_statements(statement.orelse, dict(loop_variables), attribute_ids, sequence)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                _scan_expression(item.context_expr, loop_variables, attribute_ids, sequence)
            _scan_statements(statement.body, dict(loop_variables), attribute_ids, sequence)
        elif isinstance(statement, ast.Try):
            _scan_statements(statement.body, dict(loop_variables), attribute_ids, sequence)
            for handler in statement.handlers:
                _scan_statements(handler.body, dict(loop_variables), attribute_ids, sequence)
            _scan_statements(statement.orelse, dict(loop_variables), attribute_ids, sequence)
            _scan_statements(statement.finalbody, dict(loop_variables), attribute_ids, sequence)


def _scan_expression(
    expression: ast.AST | None, loop_variables: dict[str, str],
    attribute_ids: dict[str, str], sequence: list[tuple[str, str]],
) -> None:
    if expression is None:
        return
    if isinstance(expression, ast.Call):
        if isinstance(expression.func, ast.Attribute) and not (
            isinstance(expression.func.value, ast.Name) and expression.func.value.id == "self"
        ):
            _scan_expression(expression.func.value, loop_variables, attribute_ids, sequence)
        for argument in expression.args:
            _scan_expression(argument, loop_variables, attribute_ids, sequence)
        for keyword in expression.keywords:
            _scan_expression(keyword.value, loop_variables, attribute_ids, sequence)
        component_id = ""
        if (isinstance(expression.func, ast.Attribute)
                and isinstance(expression.func.value, ast.Name)
                and expression.func.value.id == "self"):
            component_id = attribute_ids.get(expression.func.attr, "")
        elif isinstance(expression.func, ast.Name):
            component_id = loop_variables.get(expression.func.id, "")
        if component_id and (not sequence or sequence[-1][0] != component_id):
            sequence.append((component_id, _unparse(expression, "forward module call")))
        return
    for child in ast.iter_child_nodes(expression):
        _scan_expression(child, loop_variables, attribute_ids, sequence)


def _lane_for(family: str, label: str, path: str, symbol: str, operation: str) -> str:
    normalized = " ".join((label, symbol, operation, path)).casefold()
    symbol_text = " ".join((label, symbol)).casefold()
    if "test" in Path(path).name.casefold() or any(term in symbol_text for term in ("validate_", "preflight", "ledger", "audit", "resolved_config")):
        return "diagnostics_and_accounting"
    if any(term in normalized for term in ("split", "sampler", "source", "manifest", "input", "data")) and ("data.py" in path.casefold() or "manifest" in symbol_text or "split" in symbol_text):
        return "data_and_sampling"
    if "metrics.py" in path.casefold() or any(term in symbol_text for term in ("metric", "evaluation", "endpoint", "auroc", "aggregate", "calibration", "domain_drop", "probe")):
        return "evaluation"
    objective_terms = ("objective", "constraint", "criterion", "cost", "energy", "assumption", "boundary condition", "loss", "decoder", "reconstruct", "contrastive")
    evaluation_terms = ("error", "estimate", "sensitivity", "stability", "robust", "bound", "result", "validation", "counterexample", "certificate")
    if family == "external_protocol":
        objective_terms += ("estimand", "intervention", "exposure", "coding rule", "codebook", "adjustment", "hypothesis")
        evaluation_terms += ("effect", "theme", "subgroup", "negative case", "triangulat")
    if any(term in normalized for term in objective_terms):
        return "training_objective"
    if any(term in normalized for term in evaluation_terms):
        return "evaluation"
    return "representation_model"


def _publication_name(value: str) -> str:
    text = str(value or "").rsplit(".", 1)[-1]
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = " ".join(text.replace("_", " ").split())
    replacements = {"main": "Training entry", "run": "Experiment orchestration", "run epoch": "Optimization epoch", "forward": "Shared forward path", "objective condition": "Objective conditions", "sample mask": "Valid-token masking", "approved perturber": "Audited perturbation", "perturbation audit": "Task-valid perturbation audit", "audited nonsemantic perturber": "Nonsemantic paired view", "nt xent loss": "Contrastive consistency objective", "compose objective": "Joint training objective"}
    return replacements.get(text.casefold(), text.title() if text else "Method component")


def _clean_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")[:80]


def _is_plumbing_symbol(value: str) -> bool:
    return str(value or "").rsplit(".", 1)[-1].casefold() in {"main", "run", "_run_epoch", "forward"}


def _unique_component_id(components: list[dict[str, Any]], base: str) -> str:
    existing = {str(item.get("id") or "") for item in components}
    candidate, suffix = base, 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _check_description(check: dict[str, Any]) -> str:
    from .scientific_assets import _clean_name
    return _clean_name(check.get("description") or check.get("purpose") or check.get("requirement"), "", 300)


def _safe_source(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate.is_file() and candidate.stat().st_size > 0


def _verification_symbol(candidate: Path, symbol: str) -> bool:
    return candidate.name.casefold().startswith("test_") or symbol.casefold().startswith(("test_", "validate_", "resolved_config", "run_preflight"))


def _class_method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next((item for item in class_node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name), None)


def _self_assignment(node: ast.AST) -> tuple[str, ast.AST] | None:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return None
    value = node.value
    if not isinstance(value, ast.Call) and not (
        isinstance(value, ast.IfExp)
        and any(isinstance(branch, ast.Call) for branch in (value.body, value.orelse))
    ):
        return None
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    attribute = next((target.attr for target in targets if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"), "")
    return (attribute, value) if attribute else None


def _unparse(node: ast.AST, fallback: str) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, TypeError, ValueError, RecursionError):
        return fallback


def _class_module_operations(class_node: ast.ClassDef) -> list[str]:
    init = _class_method(class_node, "__init__")
    operations = []
    for node in ast.walk(init) if init is not None else []:
        assignment = _self_assignment(node)
        if assignment is None:
            continue
        value = assignment[1]
        call = value if isinstance(value, ast.Call) else (
            value.body if isinstance(value, ast.IfExp) and isinstance(value.body, ast.Call)
            else value.orelse if isinstance(value, ast.IfExp) and isinstance(value.orelse, ast.Call)
            else None
        )
        if call is None:
            continue
        name = _unparse(call.func, "module").replace("nn.", "")
        if name and name not in operations:
            operations.append(name)
    return operations


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return ""


def _alias_targets(components: list[dict[str, Any]], class_ids: dict[tuple[str, str], str]) -> dict[str, str]:
    aliases = {}
    for item in components:
        parent, operation = str(item.get("parent_component") or ""), str(item.get("operation") or "")
        match = re.match(r"\s*([A-Za-z_][\w.]*)\s*\(", operation)
        if not parent or not match:
            continue
        target = class_ids.get((str(item.get("source_path") or ""), match.group(1).rsplit(".", 1)[-1]))
        component_id = str(item.get("id") or "")
        if target and target != component_id:
            aliases[component_id] = target
    return aliases


def _resolve_flows(flows: list[dict[str, str]], aliases: dict[str, str], resolve: Any) -> list[dict[str, str]]:
    unique, seen = [], set()
    for flow in flows:
        item = dict(flow)
        source, target = str(flow.get("from") or ""), str(flow.get("to") or "")
        if flow.get("flow_kind") == "data":
            item["from"], item["to"] = resolve(source, "output"), resolve(target, "input")
        else:
            item["from"], item["to"] = resolve(source), resolve(target)
            if target in aliases:
                item["operation"], item["flow_kind"] = "uses shared module", "module_reference"
        key = tuple(str(item.get(name) or "") for name in ("from", "to", "operation", "source_path", "source_symbol"))
        if item["from"] != item["to"] and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
