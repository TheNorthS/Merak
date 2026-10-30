"""Project frozen domain roles into public analysis headings and explicit axes."""

from __future__ import annotations

from typing import Any

from ..services.simulation_asset_profile import simulation_asset_profile


_SPECIALIZED_CONTEXT = {"eeg": "EEG", "vision": "vision model",
                        "language": "language model", "timeseries": "time series"}


def report_role_headings(
    manifest: dict[str, Any], default_headings: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Use the current domain producer's public names for declared frozen roles."""
    profile = simulation_asset_profile({
        "family": str(manifest.get("research_family") or ""),
        "study_archetype": str(manifest.get("study_archetype") or ""),
    }, context=_SPECIALIZED_CONTEXT.get(str(manifest.get("specialized_domain") or ""), ""))
    assets = {asset["completeness_role"]: asset for asset in profile["assets"].values()}
    headings, issues = {}, []
    if manifest.get("asset_domain") != profile["domain"]:
        issues.append("The declared analysis domain conflicts with its frozen research family")
    if manifest.get("specialized_domain") and manifest["specialized_domain"] not in _SPECIALIZED_CONTEXT:
        issues.append("The declared specialized analysis domain is unsupported")
    for frozen in manifest.get("domain_asset_profile") or []:
        if not isinstance(frozen, dict):
            issues.append("The registered analysis profile must contain scientific role records")
            continue
        role = str(frozen.get("stable_role") or "")
        asset = assets.get(role)
        if asset is None or frozen.get("domain_role") != asset["domain_asset_role"]:
            issues.append(f"{role}: declared domain role does not match its current public producer contract")
            continue
        public = str(asset["table_description"]).partition(" with uncertainty intervals.")[0]
        headings[role] = (default_headings[role] if manifest.get("asset_domain") == "algorithmic"
                          and not manifest.get("specialized_domain") else public)
    return headings, issues
