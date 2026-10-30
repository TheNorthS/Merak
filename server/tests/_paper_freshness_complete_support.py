"""Source-only manuscript fixture whose current local author contracts all pass."""

import json

from server.services.paper_drafting import AUTHOR_STAGE_ORDER, PaperDraftingService, SECTION_BY_ID
from server.tests._staged_paper_drafting_support import seed_project
from server.tests.test_paper_stage_validator_cache import _introduction

FIXTURE_DIRECTION = "Robust signal representation learning under held-out sensor layouts"


def completed_local_manuscript(root):
    seed_project(root)
    bibliography = root / "literature/references.bib"
    bibliography.write_text("\n".join(
        f"@article{{ref{i},title={{Verified source {i}}},author={{Author}},year={{2025}},journal={{Journal}}}}"
        for i in range(1, 41)))
    service = PaperDraftingService()
    service.prepare(root, {"research_direction": FIXTURE_DIRECTION})
    paths = service.paths(root)
    headings = ("Research Question", "Closest-Work Gap", "One-Sentence Contribution", "Mechanism Logic",
                "Claims and Required Evidence", "Alternative Explanations", "Section Narrative", "Evidence Boundary")
    paths["blueprint"].write_text("\n".join("## " + heading + "\n" +
        "The matched scientific control preserves independent units and tests the registered causal alternative. " * 8
        for heading in headings))
    _write_sections(paths)
    paths["cross_review"].write_text("## Checks Performed\nCurrent source contracts and references reviewed.\n"
                                   "## Final Consistency Verdict\nPASS\n")
    # Acceptance binds the canonical assembly normalization, not pre-assembly bytes.
    service.assemble(root)
    for stage in AUTHOR_STAGE_ORDER:
        review = service.validate_stage(root, stage)
        assert review["passed"], (stage, review["issues"])
        service.mark_stage(paths, stage, "completed", attempt=1, review=review)
    review = service.validate_complete_draft(root)
    assert review["passed"], review["issues"]
    return service, paths


def _write_sections(paths):
    citations = r"\cite{" + ",".join(f"ref{i}" for i in range(1, 41)) + "}"
    paths["title"].write_text("Topology-aware robust representation learning under held-out layouts")
    abstract = ("This protocol tests a matched representation hypothesis using independent units and held-out layouts. " * 12)
    (paths["sections"] / "00_abstract.tex").write_text(abstract)
    for stage, spec in SECTION_BY_ID.items():
        if stage == "introduction":
            text = _introduction()
        else:
            unique = {
                "related_work": "Taxonomies partition assumptions about historical alternatives, related architectures, prior objectives, sensor domains, comparative estimators, indexing abstractions, inductive biases, methodological families, acquisition regimes, and established literature boundaries.",
                "method": "Topology-aware tokenizer represents vertices, adjacency, coordinates, embeddings, neighborhoods, attention, transformations, mappings, encoders, feature spaces, gradients, parameterization, regularizers, reconstruction, optimization, prediction, inference, constraints, and objective functions.",
                "experiments": "Dataset sampling defines independent subjects, disjoint held-out splits, matched baselines, confidence interval endpoints, statistical uncertainty, accuracy metrics, compute runtime, preprocessing, seeds, acquisition, validation partitions, hardware budgets, and controls.",
                "results": "The planned protocol compares control conditions, sensitivity, component removal, registered decision rules, stress ranges, robustness, failure analysis, uncertain intervals, matched opportunities, endpoint ordering, interpretation boundaries, and alternative configurations.",
                "discussion": "Alternative explanations include unequal resource allocation; a null result would falsify the causal hypothesis. Transfer interpretation distinguishes counterfactuals, plausibility, generalization, explanations, opportunity, confounding, mechanisms, negative outcomes, and scope.",
                "limitations": "Validity threats include sampling bias, incomplete external coverage, and finite compute. Future mitigation requires additional independent cohorts, broader geography, reproducibility checks, stronger measurement, data diversity, and acquisition controls.",
                "conclusion": "The protocol answers a registered transfer question through falsifiable predictions, matched contrasts, topology reasoning, and decisive independent testing. Scientific conclusions remain conditional on future observations, replication, and uncertainty.",
            }[stage]
            title = "Evaluation Protocol" if stage == "results" else spec.title
            repeat = max(1, (spec.minimum_words + 20) // len(unique.split()) // 2 + 1)
            text = rf"\section{{{title}}}" + "\n\n" + unique * repeat + "\n\n" + unique * repeat + citations
            if stage == "related_work":
                text += r"\subsection{Representation families}\subsection{Transfer assumptions}\subsection{Evaluation criteria} Unlike the closest work, matched controls isolate the mechanism."
            if stage == "method":
                text += r"\[L = \sum_i x_i^2\] Figure~\ref{fig:method} depicts the matched topology transformation.\begin{figure}\caption{Topology mechanism}\label{fig:method}\end{figure}"
            if stage == "experiments":
                text += r"Figure~\ref{fig:evaluation-design} explains independent evaluation partitions.\begin{figure}\caption{Evaluation design}\label{fig:evaluation-design}\end{figure}"
        (paths["sections"] / spec.filename).write_text(text)


def stale_blueprint_with_changed_pending_report(service, paths, issues):
    from server.services.paper_stage_cache_revalidation import AUTOMATIC_CONSISTENCY_DIRECTIVE

    state = json.loads(paths["state"].read_text())
    state["stages"]["blueprint"].update({"status": "running", "review_passed": False,
        "validator_signature": "0" * 64, "directed_attempts": service.DIRECTED_REPAIR_ATTEMPTS,
        "directed_issue_signature": service.directed_issue_signature(issues)})
    state["stages"]["consistency"].update({"status": "running", "review_passed": False,
        "directed_attempts": service.DIRECTED_REPAIR_ATTEMPTS,
        "directed_issue_signature": service.directed_issue_signature([AUTOMATIC_CONSISTENCY_DIRECTIVE, *issues])})
    paths["state"].write_text(json.dumps(state))
    paths["cross_review"].write_bytes(paths["cross_review"].read_bytes() +
        b"\nThe current authorized report includes an additional reference check.\n")
