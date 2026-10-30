"""Propagate the researcher's delivery goal to bounded authors and plan delegates."""

from typing import Any


def research_delivery_instruction(options: dict[str, Any] | None) -> str:
    if (options or {}).get("delivery_goal") != "reviewable_draft":
        return ""
    return """

## Explicit researcher delivery goal: reviewable scientific draft
Finish a coherent, reproducible-to-the-available-evidence draft and its review record.
Preserve scientific criticism, negative findings, missing experiments and unsupported estimands.
Do not pursue a publication score or acceptance threshold by inventing evidence, changing the
study scope or repeatedly rewriting already valid prose. Reviewer scores remain honest; fix
concrete contradictions, citations, provenance and artifact defects within this stage's targets.
The manuscript must clearly bound claims to the actual evidence and disclose its generation.
No new training, dataset collection, GPU job or external service is authorized by this goal.
Ask any delegated reviewer to assess draft coherence and integrity separately from publication
merit, then preserve unresolved research limitations and complete the bounded artifact.
"""
