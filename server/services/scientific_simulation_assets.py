"""Register the complete deterministic benchmark figure pack in an asset plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .simulation_policy import simulation_manifest_contract_issues
from .simulation_presentation_policy import simulation_presentation_fields


def append_simulation_assets(
    root: Path, assets: list[dict[str, Any]], claim_ids: list[str]
) -> None:
    from .scientific_assets import _json

    manifest_path = (
        root / "experiments" / "results" / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    payload = _json(manifest_path)
    if not isinstance(payload, dict) or simulation_manifest_contract_issues(payload):
        return
    profiles = {
        str(item.get("semantic_id") or ""): item
        for item in payload.get("domain_asset_profile") or []
        if isinstance(item, dict)
    }
    existing_ids = {
        str(item.get("id") or "") for item in assets if isinstance(item, dict)
    }
    from .evidence_asset_portfolio import selected_evidence_asset_ids
    selected_idea = _json(root / "ideas/SELECTED_IDEA.json")
    publication = selected_idea.get("publication") if isinstance(selected_idea, dict) else {}
    contribution = str((publication or {}).get("contribution_type") or "")
    selected_ids = selected_evidence_asset_ids(contribution)
    for record in payload.get("figure_files") or []:
        if not isinstance(record, dict):
            continue
        asset_id = str(record.get("id") or "").strip()
        if not asset_id or asset_id in existing_ids or asset_id not in selected_ids:
            continue
        assets.append(
            _simulation_asset(
                root, manifest_path, record, profiles.get(asset_id, {}),
                claim_ids,
            )
        )
        existing_ids.add(asset_id)


def _simulation_asset(
    root: Path,
    manifest_path: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    claim_ids: list[str],
) -> dict[str, Any]:
    record = {**record, **simulation_presentation_fields(record)}
    asset_id = str(record.get("id") or "").strip()
    data_file = str(profile.get("data_file") or "").replace("\\", "/")
    data_path = (
        f"experiments/results/simulated/{data_file}" if data_file else ""
    )
    role = str(record.get("scientific_role") or "analysis")
    domain_role = str(
        record.get("domain_asset_role") or profile.get("domain_role") or role
    )
    outputs = record.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    return {
        "id": asset_id,
        "kind": "figure",
        "generation_phase": "phase_2a",
        "generation_policy": "reuse",
        "producer_kind": record["producer_kind"],
        "publication_labels": record["publication_labels"],
        "scientific_role": role,
        "publication_role": role,
        "scientific_question": str(
            record.get("scientific_question")
            or f"What does the registered {domain_role.casefold()} analysis show?"
        ),
        "claim_ids": list(record.get("claim_ids") or claim_ids[:2]),
        "source_data": [data_path] if data_path else [],
        "data_path": data_path,
        "source_path": str(record.get("source") or ""),
        "output_path": str(outputs.get("pdf") or ""),
        "intended_comparison": str(
            record.get("intended_comparison")
            or f"Registered comparison for {domain_role.casefold()}"
        ),
        "visual_encoding": str(
            record.get("visual_encoding")
            or "Point estimates with uncertainty intervals"
        ),
        "uncertainty_encoding": str(
            record.get("uncertainty_encoding")
            or "Prespecified 95% uncertainty interval"
        ),
        "evidence_status": "synthetic_preview",
        "provenance_kind": "deterministic_simulation_preview",
        "manuscript_section": "Results",
        "label": str(record.get("label") or "").strip(),
        "caption": simulation_presentation_fields({"caption": f"{domain_role} with uncertainty intervals."})["caption"],
        "required": True,
        "manuscript_eligible": True,
        "paper_selected": True,
        "submission_eligible": False,
        "canonical_asset": True,
        "simulation_manifest": manifest_path.relative_to(root).as_posix(),
    }
