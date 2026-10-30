"""Route semantic figure repairs to their single declared producers."""

from __future__ import annotations

from typing import Any


async def rebuild_deterministic_assets(
    host: Any, run: Any, node_id: str, direction: str, round_number: int,
    asset_ids: list[str],
) -> tuple[list[str], set[str]]:
    from ..services.figure_producer_policy import figure_producers

    producers, issues = figure_producers(run.project_path, asset_ids)
    if issues:
        raise RuntimeError("figure producer contract failed: " + "; ".join(issues))
    deterministic = {
        asset_id for asset_id, producer in producers.items()
        if producer == "deterministic"
    }
    model = [
        asset_id for asset_id, producer in producers.items() if producer == "model"
    ]
    if deterministic:
        await host._ensure_figure_artifacts(
            run, "Deterministic typed figure repair", direction,
            target_asset_ids=deterministic,
        )
        for asset_id in sorted(deterministic):
            await host._emit(run, "figure_deterministic_asset_rebuilt", {
                "node_id": node_id, "asset_id": asset_id,
                "round": round_number, "producer_kind": "deterministic",
            })
    return model if producers else asset_ids, deterministic
