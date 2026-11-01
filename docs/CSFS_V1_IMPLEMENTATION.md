# CSFS-v1 implementation and verification boundary

The accepted `EXPERIMENT_PLAN.md` operational table is implemented in
`server/experiment_protocols/csfs_v1/`. This is an explicitly selected reference
implementation for that frozen study, not an automatic replacement for every
EEG experiment or every research family.

## Implemented execution graph

The entrypoint checks BOTH CLI consent and configuration consent before reading
research data, constructing a model, creating an attempt, or calling an optimizer.
Importing the package and `--check` do not train, score research data, or create
results. The default exported configuration prohibits execution.

- Hash-bound local data and human legal-review evidence; common endpoint and
  label vocabulary, at least three eligible datasets, complete split identities.
- Canonical 19-channel masks, 256 Hz, 30-second windows/15-second stride,
  detrending and fourth-order zero-phase filtering; normalization fitted only on
  the permitted training partition. No dataset download or invented manifest.
- Exact half-size overlapping subsets and four channel-by-frequency composites.
- Four temporal blocks, independent linear shared/private projections, six
  symmetric InfoNCE pairs, shared/private covariance, B-side-only shuffle.
- Nine conditions, including the previously missing no-private control, matched
  actual trainable capacity, and a separate frozen-encoder affine classifier.
- 100000 source windows, checkpoint every 1000 windows, fresh 1000-update
  selection probes, earliest best validation checkpoint, registered patience,
  and one 10000-update final probe. Source sampling is dataset → subject → window.
- Recording-first then subject probability aggregation; five matched seeds
  averaged within target, target-level paired bootstrap/sign flips and C1 Holm.
- Exact paired random/region/spectral eligibility, source-validation-only anchor
  locking before target scoring, and target-local train/validation/test isolation.
- Nonfinite/missing gradients, resource ceilings, persisted heartbeats, two-OOM
  stopping with exact CPU rollback, and hash-bound complete checkpoint resume.

Source checks and artificial-fixture tests are NOT proof of real-data legality,
GPU/large-batch feasibility, empirical effectiveness, or publication readiness.
No optimizer was run on research data during implementation verification.

## Explicit implementation conventions

The registration leaves several transport/algorithm details unspecified. The
implementation makes them visible rather than claiming they were preregistered:

- Numeric local NPY recording transport, exact polyphase resampling, full-record
  linear detrending/filtering before windowing, population standard deviation,
  and omission (not padding) of incomplete final windows.
- Convolutions use stride 1, padding 7 and bias. Projection matrices are
  bias-free: a private bias is unidentifiable under centered covariance and must
  not be counted as an updated parameter. The final probe is affine with bias.
- Covariance uses sample denominator B-1. Full-latent concatenated linear heads
  and the no-private single linear head can be mathematically equivalent; no
  artificial scientific distinction is claimed between those parameterizations.
- BENDR-style context is parameter-free nearest-visible temporal context with a
  192-dimensional predictor. It is NOT the published BENDR architecture. Spans
  have length 10, with a truncated last span to meet the exact masking count;
  contrastive negatives are other batch parents at the same masked ordinal,
  avoiding an all-token quadratic matrix. Only masked-MSE targets are detached.
- Random deletion uses floor(C × percentage), nested 25/50-percent sets; ties
  between largest eligible regions follow the declared region order. Domain-local
  train/validation/test membership must be supplied explicitly, never invented.
- A condition resume reproduces the same seeded source stream and all random
  states. Downtime still counts toward wall-time/heartbeat ceilings. It cannot
  silently restart an entire study or reset spent probe/window budgets.

Signal transformations follow the [SciPy SOS forward/backward filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html)
and [polyphase resampling](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html)
interfaces. The isolated test environment uses the official
[PyTorch CPU distribution](https://pytorch.org/get-started/locally/); no
`KMP_DUPLICATE_LIB_OK` workaround or global environment modification is used.

## Copy-only export and provenance

`scripts/export_csfs_implementation.py` requires the current complete seven-file
protocol verification receipt. It creates a new `protocol-implementation-106-*`
copy and exports the trusted source bytes exactly. Obsolete implementation,
blueprint/build and workflow evidence are retained under
`.merak/implementation-history/`, not reused as current accepted states.

Scientific scene and claims stay intact; implementation selectors point to the
new canonical code. Existing numeric CSV files are preserved byte-for-byte.
`CODE_IMPLEMENTATION_ATTESTATION.json` means V1 code verification only. The
current negative readiness ledger remains unvalidated until data, resources,
consent and actual scientific execution can be independently checked. Old failed
ledger bytes are archived; no failed gate or model verdict is promoted.

## Verification boundary

Protocol tests use isolated CPU fixtures to check the implementation graph,
configuration contracts, consent checks, provenance and recovery behavior.
These checks do not certify research-data legality, GPU feasibility, empirical
performance or publication readiness.

Real-data execution requires a prepared project, validated data and resources,
and explicit execution authorization. Passing a code-only check does not make
an earlier failed or cancelled research run accepted. New production changes
require verification against their own source identity.

Local test receipts, project exports and original experiment outputs remain
outside the public source repository. Product-level release status is documented
in [RELEASE_0.1.2.md](RELEASE_0.1.2.md).
