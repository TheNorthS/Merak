"""Project declared evaluation facts into a source-bound publication protocol.

This producer projection reads explicit contract locations only. It preserves
independent holdouts and never chooses the first axis as a scientific primary.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .publication_labels import publication_metric_label
from ..contracts.evaluation import EvaluationDeclaration
from ..contracts.preparation import PreparationContractError


RUN_SOURCE = "experiments/RUN_SPEC.json"
CONFIG_SOURCE = "experiments/configs/main.yaml"


@dataclass(frozen=True)
class DeclaredEvaluationSplit:
    """One independently declared holdout, with invisible source provenance."""

    split_id: str
    display_name: str
    source_path: str
    source_symbol: str
    manifest_path: str = ""
    manifest_source_path: str = ""
    manifest_source_symbol: str = ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _axes(value: Any, source: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not _string(item) for item in value):
        raise ValueError(f"evaluation_design {source} must be a list of named holdout axes")
    axes = tuple(_string(item) for item in value)
    if len(set(axes)) != len(axes):
        raise ValueError(f"evaluation_design {source} contains duplicate holdout axes")
    return axes


def _declared_splits(
    evaluation: dict[str, Any], config: dict[str, Any], requirements: dict[str, Any],
) -> tuple[list[DeclaredEvaluationSplit], str]:
    run_axes = _axes(evaluation.get("holdout_axes"), "RUN_SPEC.evaluation.holdout_axes")
    config_axes = _axes(_mapping(config.get("evaluation")).get("holdout_axes"),
                        "config.evaluation.holdout_axes")
    if run_axes and config_axes and set(run_axes) != set(config_axes):
        raise ValueError("evaluation_design RUN_SPEC and configuration declare different holdout axes")
    axes = run_axes or config_axes
    source = RUN_SOURCE if run_axes else CONFIG_SOURCE
    manifests = _mapping(requirements.get("manifest_paths"))
    split_manifests = _mapping(requirements.get("split_manifests"))
    config_manifests = _mapping(_mapping(config.get("data")).get("split_manifests"))
    splits = []
    for index, axis in enumerate(axes):
        run_manifest = _string(split_manifests.get(axis)) or _string(manifests.get(axis))
        if _string(split_manifests.get(axis)) and _string(manifests.get(axis)) and split_manifests[axis] != manifests[axis]:
            raise ValueError(f"evaluation_design conflicting RUN_SPEC split manifest for {axis}")
        run_manifest_field = "split_manifests" if _string(split_manifests.get(axis)) else "manifest_paths"
        config_manifest = _string(config_manifests.get(axis))
        if run_manifest and config_manifest and run_manifest != config_manifest:
            raise ValueError(f"evaluation_design conflicting split manifest for {axis}")
        splits.append(DeclaredEvaluationSplit(
            split_id=axis, display_name=axis.replace("_", " ") + " held-out",
            source_path=source, source_symbol=f"evaluation.holdout_axes[{index}]",
            manifest_path=run_manifest or config_manifest,
            manifest_source_path=RUN_SOURCE if run_manifest else CONFIG_SOURCE if config_manifest else "",
            manifest_source_symbol=(f"data_requirements.{run_manifest_field}.{axis}"
                                    if run_manifest else f"data.split_manifests.{axis}"
                                    if config_manifest else ""),
        ))
    return splits, _string(_mapping(config.get("data")).get("active_holdout_axis"))


def _axis_protocol(
    protocol: dict[str, Any], evaluation: dict[str, Any], config: dict[str, Any],
    requirements: dict[str, Any],
) -> None:
    splits, active = _declared_splits(evaluation, config, requirements)
    if not splits:
        if active:
            raise ValueError("evaluation_design active_holdout_axis is absent from declared holdout axes")
        return
    protocol["declared_splits"] = [asdict(split) for split in splits]
    protocol["holdout_axes"] = [split.split_id for split in splits]
    if active and active not in protocol["holdout_axes"]:
        raise ValueError("evaluation_design active_holdout_axis is not a declared holdout axis")
    # primary_split describes scientific scope, whereas display_name is a
    # generated caption. Comparing them invents a contract no author declared.
    # Cross-source primary declarations are validated before this projection.
    # An execution axis is not a scientific primary. Only an unambiguous single
    # declared split may supply a missing primary scope.
    if len(splits) == 1 and not protocol.get("primary_split"):
        protocol["primary_split"] = splits[0].display_name
        protocol.setdefault("source_bindings", {})["primary_split"] = {
            "source_path": splits[0].source_path, "source_symbol": splits[0].source_symbol,
        }
    if active:
        protocol["active_holdout_axis"] = active


def _metric_protocol(
    protocol: dict[str, Any], evaluation: dict[str, Any], config: dict[str, Any],
    outputs: dict[str, Any],
) -> None:
    config_evaluation = _mapping(config.get("evaluation"))
    declarations = [(evaluation.get("primary_metric"), RUN_SOURCE, "evaluation.primary_metric"),
                    (outputs.get("primary_metric"), RUN_SOURCE, "scientific_outputs.primary_metric"),
                    (config_evaluation.get("primary_metric"), CONFIG_SOURCE, "evaluation.primary_metric")]
    declared = [(value.strip(), path, symbol) for value, path, symbol in declarations if _string(value)]
    if len({re.sub(r"[\s_-]+", " ", value.casefold()) for value, _, _ in declared}) > 1:
        raise ValueError("evaluation_design declared primary metrics conflict")
    metric, metric_path, metric_source = declared[0] if declared else ("", RUN_SOURCE, "")
    unit_key = _string(config_evaluation.get("analysis_unit_key"))
    if unit_key:
        protocol["analysis_unit_key"] = unit_key
        protocol.setdefault("source_bindings", {})["analysis_unit_key"] = {
            "source_path": CONFIG_SOURCE, "source_symbol": "evaluation.analysis_unit_key",
        }
    if not metric:
        return
    publication = publication_metric_label(metric)
    pooled = re.fullmatch(r"([\w.-]+)\s+pooled by\s+([\w.]+)", metric)
    if pooled and unit_key and pooled.group(2) == unit_key:
        publication = publication_metric_label(pooled.group(1)) + " (group-pooled)"
    protocol["primary_metric"] = metric
    protocol["primary_metric_publication"] = publication
    protocol.setdefault("source_bindings", {})["primary_metric"] = {
        "source_path": metric_path, "source_symbol": metric_source,
    }


def _project_evaluation_protocol(
    run_spec: Any, config: Any = None, *, plan_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Read declared split semantics without migrating or changing user artifacts."""
    spec, configuration = _mapping(run_spec), _mapping(config)
    data = _mapping(spec.get("data_dependency"))
    outputs = _mapping(spec.get("scientific_outputs"))
    requirements = _mapping(spec.get("data_requirements"))
    protocol: dict[str, Any] = {}
    for label, value in (("RUN_SPEC", spec.get("evaluation")), ("config", configuration.get("evaluation"))):
        if value is not None:
            try:
                EvaluationDeclaration.model_validate(value)
            except ValueError as error:
                raise ValueError(f"evaluation_design {label}.evaluation violates protocol v1: {error}") from error
    declarations = [(outputs.get("primary_split"), RUN_SOURCE, "scientific_outputs.primary_split"),
                    (_mapping(spec.get("evaluation")).get("primary_split"), RUN_SOURCE, "evaluation.primary_split"),
                    (_mapping(configuration.get("evaluation")).get("primary_split"), CONFIG_SOURCE, "evaluation.primary_split")]
    from .evaluation_plan_projection import split_labels_agree
    selected = [(v, p, s) for v, p, s in declarations if _string(v)]
    if selected:
        primary, path, symbol = selected[0]
        if any(not split_labels_agree(primary, value) for value, _, _ in selected):
            raise ValueError("evaluation_design primary split declarations conflict")
        protocol["primary_split"] = primary
        protocol.setdefault("source_bindings", {})["primary_split"] = {"source_path": path, "source_symbol": symbol}
    unit = (_string(outputs.get("analysis_unit")) or _string(data.get("analysis_unit"))
            or _string(requirements.get("analysis_unit"))
            or _string(_mapping(configuration.get("evaluation")).get("analysis_unit")))
    if unit:
        protocol["analysis_unit"] = unit
    required_splits = data.get("required_splits")
    if isinstance(required_splits, list):
        protocol["required_splits"] = [_string(value) for value in required_splits if _string(value)]
    for key in ("require_subject_isolation", "require_session_isolation", "require_external_group"):
        if isinstance(data.get(key), bool):
            protocol[key] = data[key]
    evaluation = _mapping(spec.get("evaluation"))
    _axis_protocol(protocol, evaluation, configuration, requirements)
    _metric_protocol(protocol, evaluation, configuration, outputs)
    from .evaluation_plan_projection import bind_plan_split

    bind_plan_split(protocol, plan_bytes)
    return protocol


def project_evaluation_protocol(run_spec: Any, config: Any = None, *, plan_bytes: bytes | None = None) -> dict[str, Any]:
    """The shared producer contract fails with structured repair ownership."""
    try:
        return _project_evaluation_protocol(run_spec, config, plan_bytes=plan_bytes)
    except ValueError as error:
        raise PreparationContractError(str(error)) from error
