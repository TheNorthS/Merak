"""Retain only declared deterministic paper-failure checkpoint classifications."""

from __future__ import annotations

from typing import Any
import json
import math
import re


def paper_runtime_failure_classification(gate: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    """A known blocking producer error can stop authoring, never grant acceptance.

    Bare flags or an arbitrary category string are not producer evidence. The
    shape here is the existing PaperPreparationError/PaperPublicationLayoutError
    gate contract; unfamiliar or accepted gates keep their normal policy.
    """
    category = details.get("error_category")
    findings = details.get("findings")
    if (gate.get("accepted") or category not in {"paper_preparation", "paper_publication_layout"}
            or details.get("retryable") is not False or not isinstance(findings, list) or not findings
            or any(not isinstance(row, dict) or row.get("severity") != "blocker" for row in findings)):
        return {}
    if category == "paper_preparation":
        valid = all(str(row.get("id") or "").startswith("PAPER-PREPARATION-")
                    and row.get("category") == "paper_preparation" and row.get("producer_kind") == "deterministic"
                    and row.get("repair_capability") == "platform_runtime" for row in findings)
    else:
        attempts = details.get("local_layout_attempts")
        valid = (details.get("stopped_for_deterministic_stage") is True and type(attempts) is int and attempts >= 0
                 and all(str(row.get("id") or "").startswith(("PAPER-PRINT-PRODUCER", "PAPER-LAYOUT-"))
                         and row.get("category") == "visual_layout" for row in findings))
    return {"error_category": category, "stopped_for_deterministic_stage": True} if valid else {}


def print_runtime_observations(raw: dict[str, Any], capability: str) -> dict[str, Any]:
    """Retain only bounded JSON observations; paths do not grant edit permission."""
    if capability != "paper-print-projection":
        return {}
    values = {key: raw[key] for key in ("producer_context", "render_attempts") if key in raw}
    _json_observation(values)
    encoded = json.dumps(values, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 32768:
        raise ValueError("Print producer observations exceed their diagnostic byte bound")
    return json.loads(encoded)


def is_paper_print_runtime_finding(raw: dict[str, Any], targets: list[str]) -> bool:
    """An exact runtime projection target is not a canonical figure editor target."""
    assets = raw.get("asset_ids")
    return bool(raw.get("id") == "PAPER-PRINT-PRODUCER" and raw.get("owner_node") == "paper"
        and raw.get("category") == "visual_layout" and raw.get("producer_kind") == "deterministic"
        and raw.get("runtime_operation") == "derive_paper_figure" and raw.get("legal_write_targets") == []
        and isinstance(assets, list) and len(assets) == 1 and isinstance(assets[0], str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", assets[0])
        and targets == [f"paper/derived-figures/{assets[0]}/PROVENANCE.json"])


def _json_observation(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("Print producer observation nesting is invalid")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_observation(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_observation(item, depth + 1)
        return
    raise ValueError("Print producer observations must be finite JSON data")
