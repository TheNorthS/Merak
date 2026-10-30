"""Prompt and gate contracts for reference-paper plus code innovation runs."""

from __future__ import annotations

from pathlib import Path


def build_innovation_system_prompt(
    node_id: str,
    project_path: str,
    options: dict,
) -> str:
    context_path = str(
        options.get("reference_context_path")
        or Path(project_path) / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json"
    )
    focus = str(options.get("innovation_focus") or "No additional focus supplied.").strip()
    return f"""## Research Mode: Reference Paper + Code Innovation
Reference context manifest: {context_path}
Innovation focus: {focus}

This is not a style-imitation task. Read the immutable project-local paper and code snapshots named
in REFERENCE_CONTEXT.json. Distinguish: (1) claims made by the paper, (2) behavior actually present
in the code, (3) gaps between them, and (4) a falsifiable novelty delta.

Scientific constraints:
- Never edit files under .merak/reference_context/snapshots/.
- Do not call a renamed module, parameter increase, or untested combination an innovation.
- Retrieve nearest-neighbor work beyond the supplied paper and explain the delta against it.
- Reproduce the supplied implementation as the reference baseline before claiming an improvement.
- Match data splits, preprocessing, budgets, metrics, and seeds between baseline and proposed method.
- Every proposed component needs an ablation or a falsification test.
- If reference reproduction fails, report that failure and do not claim superiority.
- Persist the analysis in ideas/INNOVATION_BRIEF.md and preserve traceability into experiments and paper.

Current workflow node: {node_id}."""


def build_innovation_node_input(node_id: str, project_path: str) -> str:
    root = Path(project_path)
    context = root / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json"
    intake = root / ".merak" / "reference_context" / "REFERENCE_INTAKE.md"
    brief = root / "ideas" / "INNOVATION_BRIEF.md"
    common = f"""## Mandatory reference evidence
- Context manifest: {context}
- Intake summary: {intake}
- Innovation brief: {brief}
Read the manifest first and use its snapshot paths, not the mutable source locations."""
    requirements = {
        "lit": """Read the extracted reference paper text and the reference code index. Treat the supplied
paper as a seed, then search for direct predecessors, contemporaneous alternatives, and newer nearest
neighbors inside the configured year window. In survey.md include a Reference Work Audit subsection
that separates paper claims from code-observable facts; do not infer uninspected behavior.""",
        "idea": f"""Read representative reference implementation entrypoints, configs, model code, data
pipeline, and evaluation code. Write both ideas/ideas.md and {brief}. The innovation brief must contain
these explicit sections: Reference Paper Claims; Reference Code Reality; Paper-Code Gaps; Novelty Delta;
Nearest Neighbors; Proposed Method; Baseline Reproduction; Falsification and Ablations; Claim-Evidence Map.
It must be at least 1800 characters, name the active Snapshot ID, and cite concrete snapshot file paths for code observations.""",
        "novelty": f"""Re-open {brief}, test its novelty delta against retrieved nearest neighbors, and
overwrite the brief with corrections. Reject cosmetic deltas. Record overlap, remaining delta, kill
criteria, and the minimum experiment that could falsify the contribution.""",
        "exp-design": """Use the accepted innovation brief as the experiment contract. The first block must
reproduce the reference implementation without proposed changes. Create matched baseline and proposed
configs at experiments/configs/reference_baseline.yaml and experiments/configs/proposed_method.yaml. Both configs
must include the active reference_snapshot_id from REFERENCE_CONTEXT.json.
Include controlled protocol matching, reference reproduction acceptance thresholds, full-method comparison,
component ablations, matched-capacity control, seeds, compute budget, leakage checks, and failure interpretation.
Do not replace reference behavior with a toy implementation unless explicitly labelled as an unvalidated port.""",
        "exp-run": """Run the reference baseline first. Only run the proposed method after the reproduction
contract is satisfied or explicitly record why it failed. The actual execution commands must explicitly reference
experiments/configs/reference_baseline.yaml and experiments/configs/proposed_method.yaml so runtime provenance can bind
the result files to the current configs. Persist real machine-readable outputs at
experiments/results/reference_baseline/metrics.json and experiments/results/proposed_method/metrics.json.
Never create those files with imagined values. If execution fails, leave the metric file absent and report
the failure so the deterministic gate can block unsupported downstream claims.""",
        "results": """Compare baseline and proposed outputs only under matched protocol. Audit split, seed,
preprocessing, compute, and sample alignment before computing deltas or significance. If baseline reproduction
failed or paired result files are absent, analysis.md must say that improvement is not established.""",
        "figure": """Include a paper-ready novelty-delta diagram connecting reference mechanism, code reality,
the proposed change, and falsifying experiments. Performance plots may use only the persisted baseline and
proposed metric files and must expose their source paths in the figure manifest.""",
        "narrative": """Frame the narrative around a traceable delta from the reference work. Separate
reference claims, reproduced facts, proposed changes, and experimentally supported findings.""",
        "paper": """Read INNOVATION_BRIEF.md and REFERENCE_CONTEXT.json. Include an explicit Delta from the
Reference Work subsection, a reference-baseline reproduction result/status, matched comparisons, ablations,
and limitations. If reference reproduction did not succeed, the abstract and conclusion must not claim an
improvement over the supplied work.""",
        "review": """Review the paper against the immutable reference snapshots and INNOVATION_BRIEF.md.
Reject novelty claims that do not survive nearest-neighbor comparison and performance claims made without a
successful reference reproduction under matched conditions.""",
        "audit": """Audit paper claims against paper claims, code-observed facts, the innovation brief,
baseline reproduction artifacts, proposed-method artifacts, and ablations. A missing or failed baseline
reproduction is a hard blocker for any superiority claim.""",
        "compile": """Compilation must preserve the Delta from the Reference Work and reference-reproduction
sections; page-budget edits must not remove evidence qualifiers.""",
        "ppt": """Slides must distinguish reference work, verified code behavior, proposed novelty delta,
and measured evidence. Do not present planned experiments as completed results.""",
    }
    return common + "\n\n" + requirements.get(node_id, requirements["paper"])
