# Contribution-driven publication visual system

This is the current MERAK contract. Reference papers establish a quality floor;
they are never layout templates. Figures and tables are selected from the
scientific contribution, evidence shape, research family, study archetype and
venue constraints.

## Pipeline

```text
selected idea schema 2
  -> mandatory publication semantics
  -> method contract schema 2 and scientific-scene owner gate
  -> contribution-driven asset portfolio
  -> source-grounded scientific scene
  -> domain visual grammar and renderer
  -> manuscript placement
  -> compiled-PDF geometry gate
  -> scientific review
```

## General figure portfolio and automatic subtraction

MERAK plans a *portfolio* before selecting a renderer. Each figure owns one
scientific question and one narrative level. Stable workflow artifact IDs are
kept for compatibility, while `figure_type` records the actual scientific job
for the current contribution. The supported contribution families map to
different combinations of method overview, mechanism detail, and evaluation
design; a benchmark is therefore not forced into a neural-architecture
template, and a clinical, systems, theory, simulation, or qualitative study is
not forced into an algorithm diagram.

Every planned figure receives a complexity budget:

- one primary scientific question;
- at most 7--8 primary objects;
- at most 2 primary branches (3 only where the contribution requires it);
- at most 12 visible labels, with concise publication wording;
- a minimum placed font size of 8 pt;
- `overflow_action: split` rather than font shrinking or card accumulation.

The default design portfolio has only the method overview and evaluation
protocol. A separate `core_mechanism` is planned only for an explicit contract
mandate or measured overview overflow that has a distinct internal mechanism
question. Declared independent removals each retain their own condition,
measurement path, and comparison; they are never merged into a single ablation
card for convenience.

When an authored scientific scene exceeds an object, label, or branch budget,
the layout planner records `branch_partitions`, `cross_panel_relations`, and
the exact overflow reasons. Independent method, evaluation, audit, or result
questions become companion figures; secondary statistics, limitations, and
provenance move to the caption or evidence package. Method figures do not
absorb evaluation dashboards, and evaluation figures do not repeat method
internals.

## Typed scientific figure IR

Rich-SVG figures compile from schema-2 mechanism IR. A primitive can declare
runtime-owned `subitems` for named internal alternatives such as objectives,
cohorts, conditions, proof obligations, or system components. This permits
short labels to remain deterministic even though model-authored glyphs are
text-free.

Synthesis and terminal readouts are typed instead of defaulting to a summation
loss. Supported runtime semantics include:

- `additive_objective`;
- `comparison`;
- `decision_gate`;
- `causal_merge`;
- `evidence_convergence`;
- `reported_endpoint`;
- `proof_implication`.

`output_label` states the real endpoint. The runtime renders an additive
equation only when the IR contains a real additive objective; registered
decisions, clinical endpoints, proof conclusions, and evidence convergence use
their own glyph and relation grammar. Legacy schema-2 additive equations remain
compatible, while canvas schema 13 makes stale pre-typed drafts re-prepare
explicitly.

## Production routing and ownership

Figure nature selects one producer; research domain never silently changes that
boundary:

- conceptual methods, mechanisms, systems, evidence relations, and proofs use
  `deterministic_architecture` by default: a source-bound FigureSpec is laid
  out and drawn by code;
- quantitative results use `deterministic_plot` from bound data;
- standard protocol, cohort, partition, and reporting flows use
  `deterministic_template`;
- naturalistic illustration uses `model_generated_image` when explicitly
  required.

For deterministic conceptual figures, the planner owns selection, subtraction,
scientific boundaries, and the source-grounded design brief. A model may suggest
typed semantic objects, relations, grouping, and visual grammar, but never owns
coordinates or runtime provenance. The runtime validates the suggested
FigureSpec against the frozen scientific scene and may compile it directly
from that scene when model planning is unavailable. Code owns label wrapping,
placement, connectors, typography, and SVG/PDF/PNG variants. Layout repair is
bounded and local to the producer. Hard source, semantic, safety, and output
checks remain blocking; cosmetic advice cannot strand the workflow.

`model_composed_full_svg` remains available only when explicitly declared for
a conceptual asset. In that mode the model owns the complete editable SVG and
the runtime validates XML safety, source bindings, semantic groups, visible
labels, complexity, placed font size, collision geometry, and review
provenance. SVG/PDF/PNG are derived from exactly the reviewed SVG source.

The older hybrid canvas remains supported for existing projects and for
explicitly typed runtime schematics. In that compatibility mode, the runtime
owns labels, connectors, and typed synthesis while the model owns text-free
glyphs. Primitive fragments reject `<text>`, `<marker>`, ports, and relations.
SVG conversion maps marker endpoints through nested affine transforms, so
translated, scaled, rotated, or clipped glyphs cannot leave floating triangles
at root-canvas coordinates.

The explicit `model-svg-figure` flow is:

```text
prepare_model_svg_draft
  -> model authors one complete SVG + visual blueprint
  -> submit_model_svg_draft
  -> deterministic print/collision checks
  -> native-image composition review
  -> model repairs the complete SVG
  -> accepted source_path enters generate_figure
```

The SVG, FigureSpec, scientific brief, source bundle, visual blueprint, rendered
pixels, and review are hash-bound. Any changed input invalidates acceptance.
Model-composed drafts use policy version 14. Blueprint primitives bind authored
method objects by `scientific_object_id` (or an identical stable scene ID).
The prepared `scientific_relation_contract` states required projected inputs,
primary relations, control/constraint semantics, and terminal outputs. Draft
submission and formal submission both preflight that contract before native
review. Topology preflight does not prove pixel-level arrow readability and
never invents internal loss nodes absent from the scientific owner contract.
For this source-bound route, primitive, form, flow, and blind-readback minima
follow the projected scientific scene instead of forcing four objects and
three arrows into every domain. A 2-object/1-relation method is allowed when
that is the authored story. Standalone and explicit hybrid contracts retain
their legacy floors. Native review policy 3 invalidates older cached decisions.

## Ownership-aware review and recovery

Every native-image finding is normalized to exactly one repair layer:
`planner`, `runtime`, `glyph`, or `scientific_contract`. It includes target IDs,
severity, a concrete repair action, and is persisted with the hash-bound review.
A runtime label or connector defect is never routed to a glyph-only model;
scientific relation errors return to the typed contract; overload returns to
the planner.

Best composition state persists across revision delegates together with its
canvas and mechanism IR. A regressed candidate restores the best compatible
draft, while a changed storyboard identity starts a new comparison. Revision
progress hashes active SVG parts, normalized review findings, and best-candidate
state. Meaningful draft improvement resets the no-progress counter; timestamp
or trace-path churn does not. This lets platform repair continue across process
restarts without either losing the best work or looping on a layer the active
agent cannot edit.

Figure acceptance distinguishes hard scientific and production checks from
optional visual polish. Source bindings, current hashes, safe SVG, readable
uncropped text, recoverable scientific mechanism and directed causal flow remain
blocking. Deterministic FigureSpec and protocol figures must pass local
pixel/layout/provenance checks; an explicit model-composed SVG additionally
requires independent native-image acceptance of its current pixels and valid
structured finding severity. A numerical visual score, whitespace, card
treatment, and minor stylistic preferences rank candidates or become
advisories; they cannot by themselves veto an otherwise safe figure that has
passed its producer-specific gates. A blocker or failed hard checklist item
cannot be converted into an advisory by its score. Old reviews are rechecked
under the current review policy, never silently promoted.

Deterministic conceptual and protocol figures require rendered-pixel, layout,
source, and provenance checks; their generator and skill provenance must identify
the deterministic producer. A repeated local rendering failure with unchanged
typed inputs, loaded producer implementation, SVG, and review evidence is
reported as a producer defect instead of spending another model or renderer
round on the identical artifact. A changed input or implementation reopens it.
An independently reviewed deterministic SVG with a blocking scientific finding
is subject to the same no-repeat rule only when the archived SVG/PNG and native
review trace attest the exact pixels and current review policy. Transient model
or transport errors are not cached. Public evaluation labels and must-show text
never expose internal mechanism IDs; named comparison lanes and the evaluation
split are read from declared contracts, while undeclared removals or shifts are
not drawn. Missing primary comparison or split information fails at the figure
producer instead of producing a plausible but ungrounded diagram.
Model-owned figures also have an asset-scoped automatic retry budget: after one
bounded illustration session with local and targeted resubmissions, an unchanged failed
asset is reported with its last review guidance instead of being redrawn by
every outer workflow revision. A new resume token alone cannot authorize a
fresh attempt; changed source/code or new feedback scoped to the failed asset
can. A skipped retry never counts as figure acceptance.
An unchanged exhausted model or deterministic figure attempt pauses the outer
automatic revision loop with the quality gate still unresolved. New researcher
feedback, source data, or implementation can trigger another scoped attempt.
Among unaccepted draft candidates, fewer blocking findings take priority over
a higher cosmetic score; snapshots from an old review policy cannot be restored
as current compositions.

Explicitly model-owned conceptual figures use asset-scoped visual agents:

```text
one frozen figure specification
  -> one source-bound composition brief
  -> one isolated model-composed SVG session for this asset only
  -> deterministic source, relation, print, and geometry checks
  -> native-image review with hash-bound verification memory
  -> at most two targeted resubmissions within the same session
  -> same-source SVG/PDF/PNG
  -> independent whole-figure acceptance
```

One model session never authors multiple conceptual figures. Quantitative plots
remain deterministic and data-bound. The separate three-storyboard layout
director remains only for explicit legacy/hybrid canvas use. The illustrator
cannot modify sibling assets. Source-grounded scientific relations constrain
what may be drawn, and native-image review checks whether the final pixels
communicate the required direction and conclusion. A blocked model-owned
figure retains its best draft and exact findings, but cannot enter the
paper-ready manifest.
The full-SVG delegate is hard-limited to three SVG submission calls, two
composition-review calls, and 24 agent iterations; it cannot spend another
automatic session on the unchanged asset.

The selected idea declares publication language, title, stable method/study
name, contribution type, comparator names, public claim statements, and public
mechanism names/descriptions/evaluations. Downstream translation fallbacks and
generic labels are unsupported.

`METHOD_CONTRACT.scientific_scene` contains authored public scientific objects
and source-bound data, causal, shared, control, containment, feedback, temporal,
constraint or logical relations. The runtime rejects duplicate IDs and absent
edge endpoints and selects a relation-driven layout topology. More than eight
primary objects must be partitioned rather than rendered at smaller text size.
Print-point region geometry preserves font size and avoids node overlap;
domain glyph renderers retain control of the final scientific appearance.
Source-code discovery remains an internal implementation audit, not a
publication node-coverage requirement. The model may propose a scientific
visual blueprint, but the deterministic conceptual producer owns final
geometry and output variants. The explicit full-SVG producer retains
model-owned geometry and faithful PDF/PNG variants.

The experiment-design owner validates the current method schema and scientific
scene before figure planning. Integration may add reachable implementation
evidence, but it must preserve the scene. Figure preflight revalidates this
owner contract and defers upstream instead of becoming the first component to
discover a missing scene.

Supported contribution types are model architecture, objective/mechanism,
experimental protocol, system architecture, dataset/benchmark, empirical
discovery, theory/proof, clinical/biological mechanism, and qualitative
framework. Each selects a scientific question and visual grammar, not a fixed
canvas.

Method figures carry a scene contract with bounded primary nodes/branches,
declared manuscript width, minimum placed font size and publication language.
Rich SVG review evaluates effective font size after placement, mixed-language
violations and excessive scene complexity. Repeated text cards no longer earn
quality through minimum card/text counts.

For explicitly selected model-owned SVG, the rich-SVG specialist owns
scientific semantics, public labels, visual forms,
roles, relations, annotations, and the operative formal relation. Runtime
checks reject an invalid blueprint before accepting the authored SVG.
Rich SVG now has a non-compatible schema-1 `visual_blueprint` tool input:
one focal message, narrative level, at least five source-grounded primitives
using three distinct domain-native visual forms, a reading order, and explicit
relations. Every primitive must appear as a non-text-only SVG group. A mechanism-detail
figure also declares the actual operative relation. The runtime validates
this before rendering; the native-image reviewer checks whether the pixels
really communicate it. A complex method is planned as an overview plus a
focused `core_mechanism` asset rather than a method/audit/evaluation card wall.

Publication tables reject machine field names, generic method/component labels,
placeholder factors, paragraph-length cells, and one-row standalone tables.
The freshly compiled paper is a hard gate: readable text below 8 pt, overlapping text,
content at the physical page edge, internal blank pages and orphaned headings
block paper acceptance before independent scientific review.

The semantic table compiler preserves explicit columns, grouped headings,
independent units and uncertainty notes while partitioning long tables into
bounded panels. Multi-dataset primary tables use a compact view; auxiliary
endpoints remain in the evidence package. Design tables are not forced into
every manuscript. The selected manuscript portfolio varies by contribution;
the complete seven-role simulation evidence package is not automatically a
seven-figure manuscript. Internal pairing and claim-evidence audits remain
machine-side records.

PDF geometry reports are hash-bound to both the compiled PDF and reachable
LaTeX inputs. Missing/stale reports or unverified page geometry cannot satisfy
the final paper gate. Mathematical script fonts are distinguished from tiny
publication prose and normal numeric table cells.

### Actual manuscript print scale and bounded local recovery

The paper renderer reads the reachable current template's actual text/column
width and each graphic's real insertion fraction, in PDF big points. Exported
tight bounding boxes are measured; DPI and a nominal 6.5-inch canvas cannot
attest placed readability. Unresolved dynamic TeX dimensions require explicit
measurement instead of a guessed default. The target placed font is 8.5 bp;
the existing 8 bp hard minimum remains unchanged.

Unreadable deterministic graphics receive at most two local typography/layout
attempts. Runtime-owned evaluation labels wrap with separated baselines and
monotone graph expansion; quantitative panels retain all bound rows, intervals,
labels and comparisons. No model rewrites manuscript prose to repair pixels.
Original scientific inputs, simulation manifests and source figures remain
immutable. Paper-only variants and exact graphics-only TeX overlays live under
`paper/derived-figures/`, with transactional entrypoint/receipt updates.

Acceptance recomputes the exact current source transform, template widths and
font/collision geometry. A read-only trusted re-render in memory verifies PDF
text/pixels, decoded PNG pixels and SVG pixels; re-signing output hashes alone
cannot attest scientific content. Passing cached variants may be reused only
with current complete provenance. An unchanged exhausted producer stays at a
typed, asset-specific checkpoint; changed source, implementation or placement
can authorize another bounded attempt. No failed layout is marked accepted.

Math-script classification uses adjacent mathematical glyphs and baseline
geometry. TeX small caps explicitly distinguish TeX points from PDF big points;
ordinary tiny prose or numeric table cells are not covered by that distinction.
Layout findings retain span coordinates and source-graphic identity, rather
than assigning every issue to every figure whose label happens to share a page.

The rules are domain-neutral. Domain grammars may provide signals/tensors,
services/queues, cohorts/timelines, specimens/assays, physical components,
assumptions/lemmas, or cases/themes. Renderer choice remains per asset and does
not determine scientific structure.

## Non-compatible boundary

`ideas/SELECTED_IDEA.json` schema 1 and `experiments/METHOD_CONTRACT.json`
schema 1 are unsupported. Both current contracts require schema 2. MERAK does
not migrate old research artifacts silently. Existing artifacts must be
re-authored and re-accepted by their novelty or experiment-design owner.

## Verification scope

Verification uses temporary projects, fake model providers and source-only
builders. It must include frontend type/lint checks, Python parsing, focused
contract-owner regressions and strict code-size standards. It must not run a
research workflow, model API, dataset/GPU job, simulation over user materials,
or compile a user manuscript without explicit authorization. Local checks do
not attest the publication readiness of a particular research project.
## Reader comprehension is the primary gate

The native-image reviewer judges the rendered candidate directly. It evaluates
five-second scientific comprehension, focal hierarchy, mechanism distinction,
flow, whitespace, label economy, domain-specific glyphs, visual polish, and
paper-scale readability. It returns targeted feedback while preserving strong
parts of the candidate. Candidates remain versioned; only a materially better
candidate can replace the current best.
