"""Node-owned semantic retrieval evidence, independent of other stages and clock churn."""
import hashlib
import json
from pathlib import Path


def search_evidence_snapshot(path: Path, node_id: str) -> dict:
    if node_id not in {"lit", "novelty"}:
        raise ValueError("Invalid retrieval evidence owner")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        stage = payload["stages"][node_id]
        calls = []
        for attempt in stage.get("attempts", []):
            for call in attempt.get("calls", []):
                calls.append({k: v for k, v in call.items() if k not in {"called_at", "finished_at"}})
        # Repeated persistence of the same observation is not new evidence.
        unique = sorted({json.dumps(call, ensure_ascii=False, sort_keys=True) for call in calls})
        semantic = {"run_id": payload["run_id"], "schema_version": payload["schema_version"],
                    "selected_sources": sorted(payload["selected_sources"]), "calls": unique,
                    "complete": stage.get("complete")}
        digest = hashlib.sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        digest = ""
    return {"kind": "node_search_evidence", "schema": 1, "node_id": node_id, "sha256": digest}
