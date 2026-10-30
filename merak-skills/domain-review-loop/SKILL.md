---
name: domain-review-loop
artifact-outputs: ["review-stage/REVIEW_STATE.json"]
description: Run bounded, independent, discipline-aware peer review and targeted revision against the manuscript type, target venue, reporting standard, evidence status, and study archetype. Use for submission-readiness review across computational, biomedical, natural, social, engineering, theoretical, and qualitative research.
---

# Domain Review Loop

The MERAK coordinator owns rounds, persistence, model separation, and stopping. Apply this policy inside each isolated review or fix session.

## Review procedure

1. Read the manuscript and raw project artifacts directly, including `paper/PUBLICATION_STYLE.json`, evidence map, methods/study contract, result provenance, bibliography, figure manifest, and relevant specialist artifacts.
2. Review against the declared target venue and reporting standard. Do not apply a NeurIPS-style baseline/ablation rubric to a trial, cohort, omics study, laboratory experiment, theorem paper, systems artifact, simulation, or qualitative study unless those criteria genuinely apply.
3. Evaluate significance, novelty, methodological or formal soundness, evidence sufficiency, statistics or proof validity, alternative explanations, reproducibility, ethics/governance, clarity, and artifact consistency.
4. Verify manuscript claims against raw evidence. Flag invented citations, values, approvals, sample sizes, proof status, cherry-picking, leakage, post-hoc outcome changes, missing negative results, and figure/table mismatches.
5. Separate stage readiness from publication readiness. A design-only manuscript can be ready for the next workflow stage while still being not ready for empirical submission.
6. Return the coordinator's requested JSON exactly: score, verdict, strengths, weaknesses, and prioritized action_items. Each action item must name the responsible artifact and the minimum repair or evidence needed.

## Revision procedure

Implement only accepted action items. Preserve evidence boundaries, null findings, frozen upstream contracts, citations, and the target manuscript type. Do not raise the score by deleting contrary evidence, weakening the audit, adding filler, or fabricating results.

Stop when the coordinator's threshold is met or its bounded round limit is reached. Never create a nested review loop.
