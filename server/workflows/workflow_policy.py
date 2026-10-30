"""Canonical workflow budgets, artifact contract versions, and input policies.

Versions are per owner so unrelated orchestration changes do not invalidate all
accepted nodes. Renderer selection is system-owned; obsolete UI modes are errors.
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_HUMAN_CHECKPOINT_NODES = ("exp-design", "exp-run", "paper")

REVISION_GATE_SIGNATURE_VERSION = 18

WORKFLOW_TOOL_CONTRACT_VERSION = 11

NODE_RUNTIME_CONTRACT_VERSIONS = {
    "exp-design": 10,
    "exp-run": 5,
    "results": 3,
    "figure": 12,
    "narrative": 3,
    "paper": 6,
    "review": 3,
    "audit": 2,
    "compile": 1,
    "ppt": 2,
}

AUTONOMOUS_REVISION_ROUNDS = 6

MIN_AUTONOMOUS_REVISION_ROUNDS = 1

MAX_AUTONOMOUS_REVISION_ROUNDS = 12

MANAGED_EXPERIMENT_DIRECT_HASH_LIMIT_BYTES = 64 * 1024 * 1024

MANAGED_EXPERIMENT_SNAPSHOT_MODE = "managed-experiment-contract-v1"

SEMANTIC_RESULTS_SNAPSHOT_MODE = "semantic-results-v1"

RISK_AUDIT_ACCEPTANCE_CACHE_VERSION = 1

WORKFLOW_ILLUSTRATION_MODES = frozenset({"auto"})

def normalize_revision_rounds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = AUTONOMOUS_REVISION_ROUNDS
    return min(
        MAX_AUTONOMOUS_REVISION_ROUNDS,
        max(MIN_AUTONOMOUS_REVISION_ROUNDS, parsed),
    )

def normalize_workflow_illustration_mode(value: Any) -> str:
    """Accept only current system-owned routing, never silently migrate a selector."""
    normalized = "auto" if value is None else str(value).strip().casefold()
    if normalized not in WORKFLOW_ILLUSTRATION_MODES:
        raise ValueError(f"unsupported illustration_mode: {normalized}")
    return normalized

LITERATURE_SOURCE_TOOLS: dict[str, str] = {
    "arxiv": "arxiv_search",
    "semantic_scholar": "semantic_scholar_search",
    "openalex": "openalex_search",
    "pubmed": "pubmed_search",
    "web": "WebSearch",
    "gemini": "mcp__gemini-cli__search",
    "zotero": "mcp__zotero__search",
    "obsidian": "mcp__obsidian-vault__read",
}

LITERATURE_SEARCH_NODES = frozenset({"lit", "novelty"})

LITERATURE_FETCH_SOURCES = frozenset({
    "arxiv", "semantic_scholar", "openalex", "pubmed", "web", "gemini",
})

LITERATURE_SEARCH_ERROR_RE = re.compile(
    r"^(?:search failed|arxiv (?:api|transport|response parse|query) error|"
    r"arxiv search failed|s2 api error|exa search failed|"
    r"openalex api error|openalex search failed|pubmed api error|pubmed search failed|"
    r"no search api configured|zotero search failed|obsidian read failed|"
    r"gemini search failed|http error|tool_schema_error)",
    re.IGNORECASE,
)
