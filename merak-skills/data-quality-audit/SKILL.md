---
name: data-quality-audit
description: Audit data, samples, corpora, measurements, labels, splits, batches, provenance, exclusions, and leakage risks using discipline-appropriate checks. Use before experiment execution or analysis across quantitative and qualitative research.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Data Quality and Provenance Audit

Write the exact artifact path supplied by the invocation contract. Inspect only files that exist; discover with Glob before Read.

## Audit dimensions

- Source provenance, licenses or consent constraints, versions, checksums, and acquisition dates.
- Inclusion, exclusion, deduplication, missingness, label or coding quality, batch/site/device effects, and outliers.
- Train/validation/test, cohort, case, temporal, spatial, participant, specimen, or corpus independence as applicable.
- Preprocessing fit scope and leakage paths.
- Biological versus technical replicates, repeated measurements, clustered observations, or qualitative source triangulation as applicable.
- Exact blockers, executable checks, owners, and expected evidence files.

## Required sections

- # Data Quality and Provenance Audit
- ## Available Inputs
- ## Provenance and Eligibility
- ## Independence and Leakage
- ## Quality-Control Checks
- ## Domain-Specific Risks
- ## Blockers and Required Evidence

Use PASS / WARN / BLOCKED per check. Absence of data is BLOCKED for execution but is not permission to fabricate it.
