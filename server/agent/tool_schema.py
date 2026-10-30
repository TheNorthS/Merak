"""Validate tool contracts before side effects; never coerce model arguments.

Diagnostics include schema locations and constraints, never argument values.
Schemas are local-only and checked once at tool registration.
"""
from __future__ import annotations

import copy
import inspect
import json
from functools import lru_cache
from itertools import islice
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry


@lru_cache(maxsize=256)
def _validator(encoded: str) -> Draft202012Validator:
    schema = json.loads(encoded)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=Registry())


def prepare_tool_schema(parameters: dict, handler: Callable) -> dict:
    """Reject registry drift at startup, and close the model-facing kwargs."""
    schema = copy.deepcopy(parameters)
    schema.setdefault("additionalProperties", False)
    if schema.get("type") != "object":
        raise ValueError("Tool parameters must declare an object schema")
    properties = schema.get("properties", {})
    if set(schema.get("required", [])) - set(properties):
        raise ValueError("Required tool parameters must have explicit property schemas")
    signature = inspect.signature(handler)
    accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
    if not accepts_kwargs:
        unknown = set(properties) - set(signature.parameters)
        if unknown:
            raise ValueError(f"Tool schema has unsupported handler parameters: {sorted(unknown)}")
    runtime_parameters = {"project_path", "parent_context", "workflow_node_id", "generator_skill"}
    missing = {p.name for p in signature.parameters.values()
               if p.default is p.empty and p.kind not in {p.VAR_POSITIONAL, p.VAR_KEYWORD}}
    missing -= set(schema.get("required", [])) | runtime_parameters
    if missing:
        raise ValueError(f"Tool schema omits required handler parameters: {sorted(missing)}")
    _validator(json.dumps(schema, sort_keys=True))
    return schema


def argument_issues(parameters: dict, arguments: dict) -> list[dict[str, Any]]:
    """Return bounded, value-free JSON-pointer diagnostics for the model."""
    validator = _validator(json.dumps(parameters, sort_keys=True))
    issues = []
    for error in islice(validator.iter_errors(arguments), 8):
        pointer = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1")
                                  for p in error.absolute_path)
        issue = {"path": pointer, "rule": error.validator, "expected": error.validator_value}
        if error.validator == "required":
            issue["missing"] = [p for p in error.validator_value if p not in error.instance]
        issues.append(issue)
    return issues
