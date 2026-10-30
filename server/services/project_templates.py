"""Explicitly non-executable initial files for a new research project."""

from __future__ import annotations

import json

from .research_contract_versions import METHOD_CONTRACT_SCHEMA


def _experiment_plan(direction: str) -> str:
    return f"""# Experiment Plan

> Non-executable planning scaffold for `/experiment-bridge`.

**Problem**: {direction or "[What problem does your method solve?]"}
**Method Thesis**: [One-sentence description of your approach]

## Claim Map

| Claim | Why It Matters | Minimum Convincing Evidence | Linked Blocks |
|---|---|---|---|
| C1: [Main claim] | [Why] | [Evidence needed] | B1, B2 |
| C2: [Supporting claim] | [Why] | [Evidence needed] | B3 |

## Experiment Blocks

### Block 1: Main Result
- **Claim tested**: C1
- **Dataset / split / task**: [configured study data]
- **Compared systems**: [proposed method and matched baselines]
- **Metrics**: [registered primary and secondary endpoints]
- **Setup details**: [model, optimization, budget, and seeds]
- **Success criterion**: [registered minimum effect]
- **Failure interpretation**: [scientific meaning of a negative result]
- **Priority**: MUST-RUN

### Block 2: Component Study
- **Claim tested**: C1 (mechanism isolation)
- **Compared systems**: [full method and matched component removals]
- **Success criterion**: [registered component effect]
- **Priority**: MUST-RUN
"""


def _selected_idea() -> str:
    return json.dumps({
        "schema": 2, "status": "unresolved", "title": "",
        "problem_statement": "", "hypothesis": "", "claims": [],
        "mechanisms": [], "falsification_conditions": [],
        "publication": {
            "language": "en", "title": "", "method_name": "",
            "contribution_type": "", "comparator_names": [],
        },
    }, ensure_ascii=False, indent=2) + "\n"


def _method_contract() -> str:
    return json.dumps({
        "schema": METHOD_CONTRACT_SCHEMA,
        "status": "scaffold_only",
        "selected_idea": "",
        "idea_contract_path": "ideas/SELECTED_IDEA.json",
        "idea_contract_sha256": "",
        "mechanism_coverage": [],
        "claim_evidence_plan": [],
        "implementation_checks": [],
        "evaluation_contract": {
            "primary_outcomes": [], "comparators_or_controls": [],
            "component_tests": [], "failure_conditions": [],
        },
        "scientific_scene": {"schema": 1, "objects": [], "relations": []},
    }, ensure_ascii=False, indent=2) + "\n"


def _ideas(direction: str, venue: str) -> str:
    return f"""# Research Ideas

> Non-executable idea scaffold. `/idea-discovery` must replace this content.

## Research Direction
{direction or "[Fill in your research direction]"}

## Target Venue
{venue}

## Candidate Contract
- **Core Hypothesis**: [falsifiable hypothesis]
- **Technical Approach**: [mechanism and implementation path]
- **Expected Contribution**: [claim-level novelty delta]
- **Feasibility**: unresolved
- **Novelty Status**: unresolved
"""


def _research_brief(direction: str, venue: str) -> str:
    return f"""# Research Brief

## Direction
{direction or "[Describe your research question]"}

## Key Questions
1. What is the current state of the art?
2. What are the main unsolved challenges?
3. Which evidence gap is falsifiable?

## Search Configuration
- Keywords: unresolved
- Year range: unresolved
- Venues: {venue or "unresolved"}
- Languages: English
"""


EDIT_WHITELIST = """# Edit whitelist for bounded paper improvement
allowed_paths:
  - "paper/main.tex"
  - "paper/sections/*.tex"
blocked_paths:
  - "literature/"
  - ".merak/"
  - "experiments/EXPERIMENT_PLAN.md"
"""


def research_templates(
    name: str,
    direction: str,
    venue: str,
) -> dict[str, str]:
    del name
    return {
        "experiments/EXPERIMENT_PLAN.md": _experiment_plan(direction),
        "ideas/SELECTED_IDEA.json": _selected_idea(),
        "experiments/METHOD_CONTRACT.json": _method_contract(),
        "ideas/ideas.md": _ideas(direction, venue),
        "literature/RESEARCH_BRIEF.md": _research_brief(direction, venue),
        ".merak/edit_whitelist.yaml": EDIT_WHITELIST,
    }
