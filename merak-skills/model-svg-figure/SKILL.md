---
name: model-svg-figure
description: "Design one source-grounded publication concept figure as a complete editable SVG. The model owns typography, arrows, spacing, and composition; the runtime validates and reviews without rebuilding the layout."
allowed-tools: Read, Glob, Grep, prepare_model_svg_draft, submit_model_svg_draft, draft_print_diagnostics, review_figure_svg_composition, generate_figure, figure_manifest
---

# Model-Composed Scientific SVG

Create exactly one complete, editable publication SVG for the assigned artifact.
This skill is for conceptual figures: method overviews, mechanisms, system
architectures, evidence relationships, biological pathways, apparatus, and
proof structures. Quantitative plots and standard reporting protocols belong
to their deterministic producers.

The model owns the entire visible composition, including labels, equations,
arrows, ports, whitespace, hierarchy, and domain glyphs. The runtime owns only
source binding, safety checks, XML and semantic validation, paper-scale
geometry, same-source PDF/PNG rendering, visual review, and manifest
persistence. Do not call the hybrid canvas primitive tools.

## Required sequence

1. Read `figures/FIGURE_SPECS.json` and locate the exact assigned artifact.
   Confirm `production_strategy=model_composed_full_svg`,
   `composition_owner=model`, and `full_svg_authority=true`.
2. Call `prepare_model_svg_draft`. Treat its scientific question, content
   boundary, scene, labels, source bindings, and placement limits as
   authoritative.
3. Read only the declared source paths needed for included scientific facts.
   Excluded or companion-figure material must not return. Check conditional
   mechanisms against configuration and implementation evidence. An unset
   joint head or zero joint loss weight cannot be shown as an active joint
   training/GRL branch; a separately declared frozen-downstream probe may be
   shown after encoder training. If the figure specification contradicts the source, report the
   conflict instead of drawing an unsupported mechanism.
4. Design one compact composition directly from the source-bound scientific
   subscene. A selected storyboard is used only for an explicit legacy/hybrid
   route; do not generate three alternatives for model-composed SVG. Preserve
   required source relations while simplifying the visible scene.
5. Design a schema-1 `visual_blueprint` with one question and one focal message.
   Use the prepared `visual_blueprint_contract` minima exactly. For a
   source-scoped scene, every projected object and required relation must be
   represented, but a compact 2-object/1-edge or 3-object/2-edge scene must not
   invent padding objects or decorative relations. Legacy standalone blueprints
   retain their four-primitive, three-form, four-step, three-relation floor.
   Bind each required authored object using `scientific_object_id` (or its
   exact source-scene id as the primitive id), following the prepared
   `scientific_relation_contract`. Preserve required input, output, and
   control/constraint directions. Do not add a scientific relation between
   bound objects that their owner scene does not declare. An overview may
   keep a source-authored operation compact; do not invent un-authored loss
   internals solely to fill the visual budget.
6. Author the complete SVG in one source string. Wrap every blueprint primitive
   in a stable `<g id="...">`. Text, arrows, equations, and layout may be
   authored directly because this mode grants full-SVG authority.
7. Build `element_mappings` for the scientific groups actually drawn. Every
   `element_id` must exactly match a blueprint primitive and SVG group; every
   `source_path` must be selected from the prepared mapping candidates. The
   candidates are an allowed source set, not a requirement to draw every scene
   object. Call `submit_model_svg_draft` with the SVG, blueprint, and mappings,
   then run `draft_print_diagnostics` and `review_figure_svg_composition`.
8. Modify and resubmit the complete SVG to repair findings, with at most three
   complete submissions in this one session (initial, local repair, targeted
   visual repair). Preserve strong
   parts; do not rename the artifact or create a sibling substitute. Use the
   exact labels and owning groups from text-geometry diagnostics. If a
   revision is rolled back, read and edit the restored best source, its
   `visual-blueprint.json`, and restored `element_mappings` in the manifest.
   A local failure may describe a rejected later candidate; use its exact
   labels to avoid repeating that failure while repairing the restored source.
   A cached
   review of an identical SVG requires a changed source, not another review
   call. Keep labels at publication size while fixing collisions.
9. Only after review returns `accepted`, call `generate_figure` with the staged
   `source_path`, `figure_type=rich_svg`, exact artifact id, metadata, and the
   same blueprint. The runtime carries the verified staged mappings into formal
   rendering automatically. Verify the manifest before reporting completion.

## Exact visual-blueprint vocabulary

Use the exact tokens returned by `prepare_model_svg_draft` under
`visual_blueprint_contract`. They are also enforced by the tool schema.

- `visual_form`: `signal`, `tensor`, `matrix`, `equation`, `graph`, `timeline`,
  `spatial_map`, `apparatus`, `cohort`, `distribution`, `state_trace`,
  `algorithm`, `proof`, `qualitative_map`, `table_inset`, `constraint`.
- Flow `kind`: `data`, `causal`, `control`, `constraint`, `comparison`,
  `logical`.
- Primitive `role`: `source`, `context`, `focal_process`, `interaction`,
  `control`, `constraint`, `synthesis`, `readout`, `output`.
- `narrative_level`: `method_overview`, `mechanism_detail`, or
  `study_protocol`.

Visual appearance is not a new `visual_form`. For example, draw a waveform but
classify it as `signal`; draw a token grid as `tensor` or `matrix`; represent a
comparison node using `graph`, `distribution`, or `table_inset` according to
its scientific meaning. Never submit shape or prose aliases such as
`waveform`, `signal_trace`, `token_grid`, `comparison_node`, `diamond`,
`bar_chart`, or `arrow`.

Storyboard connection kinds are layout vocabulary, not blueprint flow kinds.
Convert them before submission using these defaults:

- `main` -> `data`
- `constraint` -> `constraint`
- `feedback` -> `control`
- `side_output` -> `data`

Use `causal`, `comparison`, or `logical` instead only when the source-backed
scientific meaning calls for it. Never copy `main`, `feedback`, or
`side_output` into a blueprint flow.

## Simplicity contract

- One figure answers one scientific question.
- Prefer the smallest source-grounded scene, normally no more than 7 primary
  objects and two focal branches; never invent objects to satisfy a count.
- Use short 1--4 word labels; explanation belongs in the caption.
- Build one dominant hierarchy, not a wall of equal rounded cards.
- Use connectors only for real scientific relations.
- Avoid decorative arrows, repeated prose, duplicate legends, rainbow
  palettes, gradients, shadows, and ornamental containers.
- Method overviews exclude validation dashboards and result endpoints.
- Mechanism details exclude full study protocol and downstream evaluation.
- If content cannot fit at 8 pt, use the portfolio's companion asset instead of
  shrinking text.

## Scientific and source integrity

- Every visible scientific primitive traces to a declared source.
- Never invent values, datasets, cohorts, mechanisms, theorem status,
  implementation names, or causal claims.
- Mathematical relations must exist in the contract; never create a convenient
  summation merely to finish the composition.
- Preserve publication language and public scientific names.
- Keep workflow IDs, paths, hashes, readiness states, and claim IDs invisible.

## SVG contract

- Complete native SVG only; no script, external URL, `<image>`,
  `<foreignObject>`, iframe, base64 payload, or JavaScript.
- Use a white background, restrained colorblind-safe palette, explicit
  `viewBox`, and safe margins.
- IDs are unique. Blueprint groups contain substantive geometry, not text alone.
- Connectors terminate at intended objects and avoid labels.
- Effective placed text meets the declared minimum, normally 8 pt.
- The SVG remains the single source for SVG, PDF, and PNG.

If the third version is not accepted, preserve the strongest staged candidate
and report the remaining findings; never bypass review or start a second
automatic illustration session for the same unchanged asset.
