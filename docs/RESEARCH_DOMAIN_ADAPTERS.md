# Research-domain adapters

MERAK uses a two-level contract so a project is not silently treated as an EEG
or machine-learning benchmark:

1. `publication_style.py` classifies the research family and study archetype.
2. `experiment_implementation_build.py` maps that classification to an
   implementation family and passes the corresponding evidence contract to
   each staged code-generation session.

## Covered research families

| Research family | Default implementation path | Typical evidence and visual emphasis |
| --- | --- | --- |
| Machine learning | `machine_learning` | split-safe units, multi-seed intervals, matched ablations, calibration/efficiency |
| Computer systems | `computational_general` | workload manifest, warm-up/repetition, tail latency, scaling and failure analysis |
| Computational biology | `computational_general` | cohort/sample provenance, batch/QC, multiplicity control, external cohort/pathway validation |
| Clinical and biomedical | `external_protocol` | participant flow, prespecified endpoints, calibration/utility, subgroup and external validation |
| Experimental natural science | `computational_general` | replicate registry, instrument settings, negative controls, dose/time response and orthogonal validation |
| Social and behavioral science | `external_protocol` | sampling frame, codebook, clustered uncertainty, specification and heterogeneity analysis |
| Engineering and robotics | `computational_general` | testbed/operating-condition manifest, repeated runs, stress/failure and resource frontiers |
| Theory and formal methods | `formal_verification` | definitions/assumptions, proof dependency, checker/version, bounds and counterexamples |
| Qualitative and humanities | `external_protocol` | sampling rationale, coding trace, excerpts-to-themes, negative cases and reflexive audit trail |
| Generic quantitative research | `computational_general` | declared analysis unit, estimand uncertainty, robustness and result checksums |

## Reporting guidance used by the contracts

The built-in profiles link to established reporting guidance when applicable:
CONSORT (trials), STROBE (observational cohorts), TRIPOD/STARD (diagnostic and
prognostic models), MIAME/MINSEQE and FAIR (omics), ARRIVE (animal experiments),
COREQ/SRQR (qualitative work), and verification/validation/uncertainty
quantification guidance for simulations. These links are advisory context for
the model; deterministic gates still require the project artifacts themselves.

## Important behavior

- Protocol and formal projects are no longer treated as “not applicable” and
  silently skipped. They use the same resumable ownership and fingerprint
  machinery, but their validators look for protocol/endpoint or proof/bound/
  counterexample semantics instead of optimizer steps.
- Evidence mode preserves a domain-appropriate manuscript structure, but changes
  what the text may claim. Synthetic-preview values require explicit construction
  and scope explanations plus the final disclosure; they cannot be described as
  actual model training, clinical, field or production measurements. Sidecar
  eligibility records supplement these reader-visible limits.
- EEG-specific assets (channels, montage, topographic views) are an optional
  visualization adapter. They do not define the implementation or paper
  contracts for other fields.

The machine-readable source of truth is the `domain_evidence_contract` field in
`paper/PUBLICATION_STYLE.json` and
`experiments/IMPLEMENTATION_BLUEPRINT.json`.

These are available profile routes, not a claim that all listed families have
passed repeated real-model end-to-end acceptance. See the current
[release verification scope](RELEASE_0.1.1.md).
