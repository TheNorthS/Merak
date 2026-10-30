---
name: domain-novelty-check
allowed-tools: Read, Write, WritePart, AssembleDocument, Edit, Glob, Grep, arxiv_search, semantic_scholar_search, openalex_search, pubmed_search, WebSearch, WebFetch, verify_citation
artifact-outputs: ["ideas/novelty_report.md","ideas/SELECTED_IDEA.json"]
artifact-contracts: {"ideas/SELECTED_IDEA.json": 2}
description: Audit novelty and select a research idea using discipline-specific prior art, evidence standards, and falsification criteria. Use after idea generation for computational, clinical, biological, natural-science, social, systems, theoretical, or qualitative research.
---

# Domain Novelty Check

Produce `ideas/novelty_report.md` and a valid `ideas/SELECTED_IDEA.json`.

## Procedure

1. Read the publication profile, idea candidates, literature survey, references, search evidence, and patent prior art when enabled.
2. Compare each serious candidate with the nearest prior work on problem, mechanism, data or material, setting, endpoint, validation, and claimed contribution. A topical difference alone is not novelty.
3. Use the selected structured databases and report unresolved coverage gaps. Never claim a source was searched from prose alone; runtime search evidence is authoritative.
4. Distinguish methodological novelty, empirical discovery, theoretical contribution, dataset/resource contribution, system contribution, and translational contribution. Apply only the types valid for this profile.
5. Reject or narrow candidates when simpler alternatives, known methods, confounding, weak identification, missing controls, or infeasible validation defeat the central claim.
6. Select the strongest defensible idea and write a traceable novelty report with nearest-work matrix, surviving delta, decisive experiment or proof, risks, and rejection conditions.

## Selected idea contract

Write JSON with `schema: 2`, `status: "accepted"`, `title`, `problem_statement`, `hypothesis`, non-empty `claims`, non-empty `mechanisms`, non-empty `falsification_conditions`, and a complete `publication` object. Every claim requires stable `id`, `statement`, and `publication_statement`; every mechanism requires stable `id`, `name`, `description`, `publication_name`, `publication_description`, `publication_evaluation`, and `required`. The accepted title must appear verbatim in the novelty report. The publication object requires `language`, `title`, `method_name`, `contribution_type`, and non-empty public `comparator_names`. Schema 1 and compatibility fields such as `contract_version: schema-1` are unsupported; do not rewrite an older persisted contract—report it to the novelty owner.

Do not invent bibliographic metadata, search coverage, evidence, approvals, or results.
