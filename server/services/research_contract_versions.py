"""Current research-artifact schema versions.

These constants are the only supported write and validation versions. Persisted
older schemas fail closed; the workflow never rewrites them as a compatibility
migration.
"""

from typing import Final

SELECTED_IDEA_SCHEMA = 2
METHOD_CONTRACT_SCHEMA = 2
SCIENTIFIC_SCENE_SCHEMA = 1

CURRENT_RESEARCH_ARTIFACT_SCHEMAS: Final[dict[str, int]] = {
    "ideas/SELECTED_IDEA.json": SELECTED_IDEA_SCHEMA,
    "experiments/METHOD_CONTRACT.json": METHOD_CONTRACT_SCHEMA,
    "experiments/RUN_SPEC.json": 1,
    "experiments/IMPLEMENTATION_BLUEPRINT.json": 1,
    "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json": 1,
    "experiments/IMPLEMENTATION_BUILD.json": 1,
    "experiments/results/ANALYSIS_BUILD.json": 1,
    "experiments/results/simulated/SIMULATION_MANIFEST.json": 11,
    "figures/SCIENTIFIC_ASSET_PLAN.json": 2,
    "figures/FIGURE_SPECS.json": 4,
    "figures/FIGURE_MANIFEST.json": 1,
    "paper/tables/TABLE_MANIFEST.json": 3,
    "paper/PAPER_BUILD.json": 1,
    "audit-results/AUDIT_RESULTS.json": 5,
    "slides/SLIDE_BUILD.json": 1,
}
