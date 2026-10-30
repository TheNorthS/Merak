---
name: domain-paper-write
artifact-outputs: ["paper/main.tex","paper/sections/"]
description: Draft publication-ready manuscript sections using a discipline-aware publication profile, reporting standard, frozen paper plan, evidence map, citations, and scientific assets. Use for journals and conferences across computational, biomedical, natural, social, engineering, theoretical, and qualitative research.
---

# Domain Paper Writing

The workflow invokes this skill section by section. Edit only the canonical section or files named in the bounded invocation contract.

## Required preparation

Read the existing files named by the stage's authoritative input inventory: normally `paper/PUBLICATION_STYLE.json`, `paper/PAPER_PLAN.md`, `NARRATIVE_REPORT.md`, `literature/references.bib`, the accepted method/study artifacts, result analysis, and figure manifest. Read an evidence map only when the inventory proves that it exists (the canonical audit map is `.merak/research_audit/PAPER_EVIDENCE_MAP.json`); never probe the obsolete `paper/EVIDENCE_MAP.json` alias. Read already accepted manuscript sections before continuing the argument.

## Writing contract

1. Follow the target venue, manuscript type, reporting standards, section emphasis, terminology, citation style, anonymity requirements, and page budget in the publication profile.
2. Write a scientific manuscript, never a workflow report. Exclude internal gate language, C1/M1 labels, status badges, retry history, placeholder instructions, and platform implementation details from the paper body.
3. Make every contribution concrete and traceable. Distinguish methodological, theoretical, empirical, system, resource, and translational contributions; claim only applicable types.
4. Methods must define enough detail for the discipline: population/problem class, units, materials/data, acquisition, preprocessing, intervention/exposure/method, comparators, endpoints, analysis, uncertainty, ethics, and reproducibility as applicable.
5. Results must follow the preregistered or frozen analysis order, report denominators and uncertainty, preserve negative evidence, and cite only manifest-backed tables/figures. In ordinary design-only mode, do not narrate planned values as findings. When the invocation explicitly declares the complete deterministic benchmark track (`synthetic_preview`) and the hash-bound simulation manifest is manuscript-eligible, treat those registered scenario results as the paper's quantitative findings, use the explicit claim decisions in `claim_evidence.csv`, and do not downgrade them merely because physical experiments were disabled.
6. Discussion must address alternative explanations, external validity, limitations, failure conditions, ethics, and practical or theoretical implications without repeating the abstract.
7. Use only verified bibliography entries. Never fabricate citations, data, metrics, approvals, samples, proofs, or experiments.
8. Keep LaTeX compilable and preserve the existing template. Do not pad to hit a page target.

A non-executed design-only study may yield a rigorous protocol or methods paper and must be framed as such. The explicit deterministic benchmark track must identify its simulation design, data-generating process, fixed seed configurations and inferential limits in the scientific text. Do not describe generated values as trained empirical measurements. Simulation/simulated/synthetic are valid methodological terms; internal preview badges, workflow state and submission-status language remain excluded. The assembly service's end disclosure supplements, and never replaces, the Methods description.
