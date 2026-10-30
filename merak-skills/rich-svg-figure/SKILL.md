---
name: rich-svg-figure
description: "Author source-grounded, publication-quality method and model architecture figures as complete editable SVG scenes with faithful PDF/PNG variants. Use for paper-facing method architecture, model internals, mechanism diagrams, and domain-specific scientific pipelines where repeated generic cards are inadequate."
allowed-tools: Read, Glob, Grep, prepare_figure_svg_canvas, append_figure_canvas_primitive, replace_figure_canvas_primitive, refresh_figure_canvas_runtime, finalize_figure_svg_canvas, draft_print_diagnostics, review_figure_svg_draft, review_figure_svg_composition, generate_figure, figure_manifest
---

# Rich SVG Figure

Create one bespoke scientific visual narrative as complete editable SVG. This is the
default owner for method overviews and mechanism-detail figures. It replaces
generic FigureSpec layouts and card-wall flowcharts for paper-facing methods.

One invocation owns exactly the single artifact named by its bounded invocation
contract. Do not initialize, draw, repair, or submit sibling figures. Read the
selected storyboard from `.merak/figure-storyboards/<artifact_name>.json` and
preserve its global region hierarchy; the storyboard controls composition while
the SVG remains fully model-authored.
Implement its `connections` as visible directed or constraining scientific
relations. Never substitute a floating label, an arrow that ends in whitespace,
or a long crossing perimeter route for a declared relation. Keep the main path
continuously traceable into the synthesis/readout.

## Mandatory inputs

Before drawing, read the source paths named by the authoritative projected
subscene and the architecture/protocol bindings for those included entities.
`source_data` and `source_artifacts` are provenance supersets, not permission to
pull excluded evaluation or audit content back into this figure. For
computational work, inspect the real symbols that implement the projected
model, objective, data, and control relations. For other research families,
inspect the corresponding projected protocol, equations, apparatus, cohort,
assay, coding, or simulation contract. Never infer an internal block merely
from the paper title.

Use `SCIENTIFIC_ASSET_PLAN.json` and `FIGURE_SPECS.json` as the semantic and
caption contracts. Preserve the stable artifact id, normally
`method_architecture`.

In a workflow, `FIGURE_SPECS.json` is already persisted by the runtime with
`schema: 4`, `publication_label_schema: 1`, and a `figures` list. Read it only;
do not write a replacement schema or an `assets` list. Only draw assets with
`producer_kind: model`. Runtime-owned deterministic assets are not your targets.
Writing a plan or announcing a drawing is not completion: the assigned SVG
must pass `generate_figure` and exist in the manifest before reporting success.

## Mandatory visual blueprint

Before generating the figure, design a `visual_blueprint` object and send it in the
`generate_figure` call. This is a semantic composition contract, not a hidden
chain of thought. It must use schema 1 and contain:

- `narrative_level`: `method_overview`, `mechanism_detail`, or `study_protocol`;
- `compiler`: exactly `model-authored-svg-v1` (the runtime validates but never
  replaces the authored SVG composition);
- `focal_message`: the single visual conclusion;
- `figure_label`: a publication-facing title of ten words or fewer;
- `primitives`: five to twelve stable ids with a concise 1–6 word
  `public_label`, `scientific_meaning`, and a
  `visual_form` selected from signal, tensor, matrix, equation, graph, timeline,
  spatial_map, apparatus, cohort, distribution, state_trace, algorithm, proof,
  qualitative_map, or table_inset;
- every primitive has a domain-neutral scientific `role`: source, context,
  focal_process, interaction, control, constraint, synthesis, readout, or
  output, plus concise `annotations` that name
  visible fields, operations, switches, thresholds, or conditions;
- at least three different visual forms; a box or card is not a visual form;
- `reading_order`: at least four primitive ids;
- `flows`: at least three relations with `from`, `to`, and `kind` chosen from
  data, causal, control, constraint, comparison, or logical;
- `formal_relation` for mechanism details: an equation, operative rule,
  invariant, transformation, causal relation, or proof step actually depicted.

Method overview/detail blueprints require a focal process, a source or context,
and a synthesis, readout, or output. They do not require neural-network branches
or a merge. Study protocols require a source, a readout, and at least one
control, constraint, or focal process. Constraints encode assumptions,
eligibility, comparison guards, or conservation laws and must never masquerade
as a forward computational edge.

Materialize every primitive id as a real `<g id="...">` in the authored SVG.
Do not claim a primitive in JSON and implement it as a text-only card.

## Visual design process

1. Write a one-sentence research question the figure answers.
2. Identify the executable scientific path: inputs, interventions or
   preparation, internal method operations, representations/states, and
   outputs/readouts.
3. Identify non-forward branches. In a method overview, retain only constraints
   needed to understand the method; move evaluation, attribution, ablations,
   falsification, and endpoint registries to their own planned asset. A method
   figure is not an audit dashboard.
4. Select domain-specific glyphs. Examples include waveforms and tensors for
   signal learning; layer stacks and latent geometry for ML; cohort funnels
   and timelines for clinical studies; plates/pathways for omics; components
   and state traces for systems; meshes/fields for simulation; assumptions and
   implication structures for theory. Do not use the same icon set for every
   field.
5. Read the asset's `scene_contract` and select geometry from its scientific
   question and contribution type. There is no default canvas composition:
   linear computation, parallel contrasts, feedback, hierarchy, timelines,
   spatial topology, matrices, causal structure, and logical dependency each
   require different layouts. Do not add an in-figure title/question header
   when the manuscript caption already owns that text.
6. Trace each major visual group to a real source using a stable SVG `id` and a
   matching `element_mappings` entry.

The SVG must spend its detail budget on depicted operations, not containers.
For every branch, draw the actual compared objects, eligibility/mask rule,
operator, and branch output. For every merge, draw explicit labeled inputs and
one compact operative equation. A title plus a rounded rectangle does not count
as a mechanism. Prefer short orthogonal connectors, tight scientific insets,
and reusable SVG definitions; remove empty panels and decorative whitespace.
Use the available figure output budget to author a substantive complete scene;
do not compress a complex paper figure into a shallow 5--10 KB sketch merely
to finish the tool call.

## Source contract

Author complex rich SVG through the hybrid canvas tools; do not compress the
whole scene into one tool argument and do not choose global coordinates:

1. Before drawing, define schema-2 `mechanism_ir` with 5–12 scientific
   primitives. Each primitive declares its storyboard `region_id`, concise
   publication label, role, visual form, and one or two `semantic_cues` that
   state what a reader must recognize in its glyph (for example, paired views,
   an eligibility rule, or an operator). Declare every object-to-object
   relation in `flows`, including a concise `label` for the quantity or
   operation carried by that arrow. Every edge entering a synthesis object
   must name the source notation and any coefficient shown in the equation.
   Processing, interaction, readout, output, and synthesis objects require an
   explicit upstream relation; source, processing, interaction, and readout
   objects require a downstream relation. A synthesis must show at least two
   independently routed inputs. Never leave a loss or readout floating.
   For an additive synthesis equation, create one distinct terminal primitive
   per additive term. Its notation must be one atomic output symbol present in
   the equation, and its only downstream relation must enter the synthesis.
   Never use a shared representation object itself as a hidden loss producer.
   Call `prepare_figure_svg_canvas` with this IR. The runtime creates the
   paper-scale root, region hierarchy, primitive boxes, publication labels, and
   every connector. This IR is the method structure; do not leave M1/M2/M3 or a
   merge implicit in prose.
   The final `visual_blueprint` must reuse exactly these primitive ids, reading
   order, and flows; it cannot reinterpret the method after drawing. The
   runtime treats the mechanism IR as authoritative and canonicalizes repeated
   blueprint structure from it; use the blueprint for scientific explanation,
   not as a second independently authored graph.
2. Append each returned primitive with `append_figure_canvas_primitive` in
   reading order. `primitive_svg` contains vector geometry only, using local
   coordinates from `(0,0)` to the returned `glyph_width` and `glyph_height`.
   Do not include `<text>`, panels, labels, ports, arrows, or connectors. The
   runtime owns all scientific object names and relations. The model owns only
   the domain-native glyph inside each object box.
3. After the focal mechanism fragment is appended, call
   `review_figure_svg_draft`. Repair that fragment before adding downstream
   regions when the native-image review finds overlap, unreadable text,
   generic-card encoding, or unclear scientific operations. If it returns
   `local_repair_required`, fix the reported print-scale issue immediately;
   native-image review has deliberately not run yet.
4. `finalize_figure_svg_canvas` requires every storyboard region, XML-validates
   the assembled source, and returns a project-relative `source_path`.
5. Call `draft_print_diagnostics` and repair every reported text in its owning
   fragment. Do not add global CSS overrides or `!important` to conceal tiny
   labels; these also risk overlap and will be rejected.
6. Call `review_figure_svg_composition` with the exact final visual blueprint.
   This is the whole-figure native-image preflight. If it returns `refine`,
   preserve strong fragments, repair only the implicated fragments, finalize,
   rerun print diagnostics, and repeat the composition review. A formal
   submission without an accepted hash-bound composition review is rejected.
   `local_repair_required` can report rendered-PDF text collisions even when
   the font-size floor passed. Shorten or move the named labels; never shrink
   them below the print threshold merely to satisfy geometry.
   When every implicated fragment is runtime-owned (`mechanism_connections`,
   `canvas_region_headers`, `mechanism_frames`, or
   `mechanism_connection_labels`), call `refresh_figure_canvas_runtime` and
   review again. Do not restart the canvas or regenerate model glyphs.
   `regressed_restored` means the revision scored below the strongest staged
   composition and the runtime restored that better draft. Continue from the
   restored fragments and address only the remaining findings; do not recreate
   or reapply the rejected composition.
   If a tool reports a stale canvas or mechanism contract, immediately call
   `prepare_figure_svg_canvas` with a fresh schema-2 IR. Never review or submit
   an unaccepted draft left by an older workflow run.
7. Pass the finalized `source_path` to `generate_figure`. Do not also send
   inline `code`.

After a failed render or Reviewer verdict, preserve all strong glyphs. Use
`replace_figure_canvas_primitive` only for the named primitive implicated by
the findings, then finalize and resubmit the same asset. Object boxes, labels,
and connectors are runtime-owned and cannot be redrawn by the model. Do not call
`prepare_figure_svg_canvas` during repair unless the Reviewer explicitly finds
the entire composition unusable. Never patch a canonical accepted SVG or invent
a new semantic id.

Call `generate_figure` for the assigned semantic id with:

- `figure_type: rich_svg`
- `recommended_backend: rich_svg`
- `recommended_skill: rich-svg-figure`
- `artifact_name`: the exact `FIGURE_SPECS` id
- `description`: a nonempty, concise statement of the scientific mechanism or
  evaluation relation actually depicted; this is a required tool argument
- `source_path`: the finalized staged SVG path. The runtime preserves this
  complete editable, source-grounded scene and derives its PDF/PNG variants
  without replacing the composition
- all scientific metadata copied from the asset specification
- `element_mappings`: stable SVG group ids mapped to project-relative sources
- `visual_blueprint`: the complete schema-1 composition contract above

`element_mappings` must map the blueprint primitive ids, not every source-code
symbol discovered in the project. The authored SVG must contain those groups;
mapping undeclared ids is an error.

The bounded repair budget is three submissions for the same semantic id. A
failed renderer or reviewer response must be repaired in place; never invent a
replacement id. Do not call the tool again after it succeeds.

The visible narrative, caption, and stable `fig:` label must describe the same
mechanisms and evaluation consequence. Preserve claim links only as manifest
metadata; never draw claim IDs or code identifiers as visible labels. The paper
stage must be able to cite this exact semantic id and explain the figure without
translating a different architecture.

The backend does not execute Python or JavaScript. Submit only complete native
SVG in `code`; do not submit a Python script, FigureSpec JSON, Mermaid,
Draw.io XML, base64 image, external URL, `<image>`, `<foreignObject>`, or
`<script>`.

Every major source-grounded module should be wrapped in a group such as:

```svg
<g id="shared_temporal_encoder">
  <!-- detailed vector internals -->
</g>
```

and mapped with:

```json
{
  "element_id": "shared_temporal_encoder",
  "source_path": "experiments/src/models.py",
  "source_symbol": "ChannelAgnosticTemporalEncoder",
  "semantic_role": "shared feature encoder"
}
```

## Publication standard

- Use a white background, restrained colorblind-safe palette, dark navy text,
  light hierarchy panels, and flat vector styling.
- Start from the accepted MERAK rich-SVG color language when appropriate:
  navy `#17233C`, muted text `#52627A`, borders `#B7C3D3`, blue
  `#4E82C3/#E8F1FB`, teal `#2B9A8A/#E4F5F1`, orange
  `#E89A4A/#FFF0DF`, purple `#8B72B6/#F1ECF8`, red
  `#D9655B/#FBEAE8`, and green `#61A66A/#EAF5EA`. Use only the subset that
  carries meaning for the current method.
- Use Arial/Helvetica-compatible fonts and compute font sizes from the placed
  paper width. At 1800 viewBox units placed at 468 pt, 8 pt requires at least
  31 canvas units for the smallest label. Either use that floor or reduce the
  canvas width while preserving unclipped, balanced composition. Do not rely
  on a large PNG preview to hide unreadable paper-scale labels.
- Prefer a 900–1200-unit viewBox width for a dense double-column schematic;
  at 1200 units and 468 pt placement the 8 pt floor is about 21 units. This
  is a coordinate scale, not a prescribed layout. Keep only labels required
  to recover the scientific mechanism, and set no large display text inside
  glyph regions. Do not enlarge every label to pass the floor without
  remeasuring its available width and rendered collisions.
- Keep outer margins near 40–60 px, gaps between major panels near 20–35 px,
  and inner padding near 16–24 px. Align repeated stage tops and bottoms to
  exact shared coordinates instead of estimating each card independently.
- Encode meaning with color plus shape, placement, line style, or labels.
- Show actual internal operations. `Input → Model → Output` is never sufficient.
- Obey `maximum_primary_nodes` and `maximum_primary_branches`; split independent
  scientific questions instead of shrinking text or adding another card band.
- Size every label for the declared manuscript placement. The effective font
  after scaling must meet `minimum_placed_font_pt`, normally 8 pt.
- Construct the figure from the blueprint's scientific primitives. Overview
  figures show actual state/tensor/entity transformations. Mechanism-detail
  figures zoom into the contribution using equations, matrices, attention
  maps, causal structures, apparatus internals, spatial relations, proof
  dependencies, or equivalent domain-native objects. Prefer several purposeful
  glyph types over repeated equal-sized rounded cards. Use a container only
  when it defines a real scientific boundary.
- Use solid arrows for executable paths and restrained dashed lines for audits,
  constraints, or supervision. Route connectors through whitespace; never
  through labels, nodes, or dense glyphs.
- Keep one visual hierarchy and consistent alignment. Avoid rainbow palettes,
  gradients, 3D effects, glow, heavy shadows, clip-art, branding, and
  watermarks.
- Do not render claim IDs, workflow state, file paths, implementation
  bookkeeping, readiness gates, or provenance hashes in the paper figure.
- Do not claim empirical performance in a method architecture.

## Preflight before calling the tool

Inspect the SVG source yourself and confirm:

- all XML is valid and escaped;
- the `viewBox` encloses every element with safe margins;
- no text crosses a panel boundary;
- no connector crosses text or an unrelated module;
- repeated columns and rows align exactly;
- all source-mapped ids exist and are unique;
- the figure contains substantive scientific glyphs, not only boxes;
- the single focal mechanism can be understood in five seconds;
- terminology matches the source code and method contract exactly.

If `generate_figure` rejects the SVG, revise the same source and retry the same
artifact id. Never create a replacement filename or fall back to FigureSpec.
