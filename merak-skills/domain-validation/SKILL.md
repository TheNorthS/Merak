---
name: domain-validation
description: Design or audit discipline-specific validation beyond the primary result, including external, orthogonal, mechanistic, robustness, subgroup, proof, simulation, qualitative triangulation, or deployment validation. Use after the experiment/result contract is available.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Domain Validation Plan and Audit

Create the exact artifact requested by the invocation contract.

## Procedure

1. Read the publication profile, methodology, statistical plan when applicable, result analysis, method contract, and actual evidence manifests.
2. Select validation that can distinguish the proposed explanation from plausible alternatives. Do not add generic ablations that do not test a claim.
3. Match validation to the domain: external cohorts and calibration for clinical work; batch and orthogonal validation for omics; scale/failure/cost for systems; controls and independent assays for experiments; assumptions/counterexamples for theory; negative cases/triangulation/reflexivity for qualitative work; robustness/error slices/compute matching for ML.
4. Mark each item as EXECUTED, PARTIAL, PLANNED, NOT_APPLICABLE, or BLOCKED and cite the exact artifact path.
5. Never turn a planned test or synthetic preview into evidence.

## Required sections

- # Domain Validation Plan and Audit
- ## Validation Questions
- ## Alternative Explanations
- ## Required Validation Matrix
- ## Evidence Status
- ## Failure and Claim-Narrowing Rules
- ## Manuscript-Ready Outputs
