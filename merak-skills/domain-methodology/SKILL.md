---
name: domain-methodology
description: Build a discipline-appropriate methodology contract from the selected idea, publication profile, evidence mode, and available data or source material. Use for empirical, theoretical, computational, clinical, experimental, social-science, or qualitative research before implementation.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Domain Methodology Contract

Create the exact artifact path supplied by the invocation contract.

## Required workflow

1. Read paper/PUBLICATION_STYLE.json, ideas/SELECTED_IDEA.json, and the accepted literature and experiment artifacts that exist.
2. Identify the study family, study archetype, unit of analysis, target population or problem class, intervention/exposure/method, comparators, endpoints, assumptions, and falsification boundary.
3. Apply the reporting standard named in the publication profile. Do not substitute a machine-learning template for a clinical, omics, systems, theory, experimental, social, or qualitative study.
4. Separate fixed decisions from unresolved decisions. Never invent data availability, sample size, measurements, ethics approval, theorem status, or experimental outcomes.
5. Write a concrete methodology contract that downstream code, analysis, and manuscript stages can execute and audit.

## Required sections

- # Domain Methodology Contract
- ## Research Profile
- ## Study Question and Units
- ## Design and Comparators
- ## Measurement or Formal Objects
- ## Bias, Confounding, and Failure Modes
- ## Falsification and Decision Rules
- ## Downstream Artifact Contract

The document is a scientific design artifact, not a workflow report.
