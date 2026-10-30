"""Declarative registration table for the MERAK agent tool surface."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from server.services.rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    MAX_BLUEPRINT_PRIMITIVES,
    NARRATIVE_LEVEL_VALUES,
    SCIENTIFIC_ROLE_VALUES,
    VISUAL_FORM_VALUES,
)


ToolHandler = Callable[..., Any]
VISUAL_BLUEPRINT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Required for rich_svg: schema-1 scientific composition bound to authored SVG groups",
    "properties": {
        "schema": {"type": "integer", "enum": [1]},
        "compiler": {"type": "string", "enum": ["model-authored-svg-v1"]},
        "narrative_level": {
            "type": "string", "enum": list(NARRATIVE_LEVEL_VALUES),
        },
        "focal_message": {"type": "string"},
        "figure_label": {"type": "string"},
        "primitives": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_BLUEPRINT_PRIMITIVES,
            "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "scientific_object_id": {
                "type": "string",
                "description": "Optional explicit object id from prepare_model_svg_draft.scientific_relation_contract",
            },
            "visual_form": {"type": "string", "enum": list(VISUAL_FORM_VALUES)},
            "public_label": {"type": "string"},
            "role": {"type": "string", "enum": list(SCIENTIFIC_ROLE_VALUES)},
            "scientific_meaning": {"type": "string"},
            "notation": {"type": "string"},
            "annotations": {"type": "array", "items": {"type": "string"}},
        }, "required": ["id", "visual_form", "public_label", "role", "scientific_meaning", "annotations"]}},
        "reading_order": {
            "type": "array", "minItems": 1,
            "items": {"type": "string"},
        },
        "flows": {
            "type": "array", "minItems": 0,
            "items": {"type": "object", "properties": {
            "from": {"type": "string"}, "to": {"type": "string"},
            "kind": {"type": "string", "enum": list(FLOW_KIND_VALUES)},
        }, "required": ["from", "to", "kind"]}},
        "formal_relation": {"type": "string"},
    },
    "required": [
        "schema", "compiler", "narrative_level", "focal_message", "figure_label", "primitives",
        "reading_order", "flows",
    ],
}
ELEMENT_MAPPING_TOOL_SCHEMA: dict[str, Any] = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_BLUEPRINT_PRIMITIVES,
    "description": (
        "Bind authored visual_blueprint/SVG group ids to sources returned by "
        "prepare_model_svg_draft.element_mapping_contract.mapping_candidates"
    ),
    "items": {
        "type": "object",
        "properties": {
            "element_id": {"type": "string"},
            "source_path": {"type": "string"},
            "source_symbol": {"type": "string"},
            "semantic_role": {"type": "string"},
        },
        "required": ["element_id", "source_path"],
        "additionalProperties": False,
    },
}
FIGURE_ELEMENT_MAPPINGS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "element_id": {"type": "string"},
            "source_path": {"type": "string"},
            "source_symbol": {"type": "string"},
            "semantic_role": {"type": "string"},
        },
        "required": ["element_id", "source_path"],
    },
    "description": (
        "Map each architecture element to a real code, protocol, formula, or "
        "contract source"
    ),
}
STORYBOARD_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "topology": {"type": "string", "enum": [
            "linear", "parallel", "hierarchical", "radial", "matrix",
            "timeline", "spatial", "causal", "logical", "hybrid",
        ]},
        "focal_message": {"type": "string"},
        "regions": {"type": "array", "minItems": 2, "maxItems": 8, "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "purpose": {"type": "string"},
                "visual_grammar": {"type": "string"},
                "relative_weight": {"type": "integer", "minimum": 1, "maximum": 5},
            }, "required": ["id", "purpose", "visual_grammar", "relative_weight"],
        }},
        "reading_order": {"type": "array", "items": {"type": "string"}},
        "connections": {"type": "array", "minItems": 1, "maxItems": 16, "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "from": {"type": "string"},
                "to": {"type": "string"},
                "kind": {"type": "string", "enum": [
                    "main", "constraint", "feedback", "side_output",
                ]},
                "scientific_meaning": {"type": "string"},
            }, "required": ["id", "from", "to", "kind", "scientific_meaning"],
        }},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "id", "topology", "focal_message", "regions", "reading_order",
        "connections", "strengths", "risks",
    ],
}
MECHANISM_IR_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object", "properties": {
        "schema": {"type": "integer", "enum": [2]},
        "primitives": {"type": "array", "minItems": 5, "maxItems": 12, "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "region_id": {"type": "string"},
                "public_label": {"type": "string"},
                "role": {
                    "type": "string", "enum": list(SCIENTIFIC_ROLE_VALUES),
                },
                "visual_form": {
                    "type": "string", "enum": list(VISUAL_FORM_VALUES),
                },
                "notation": {"type": "string"},
                "subitems": {
                    "type": "array", "maxItems": 6,
                    "items": {"type": "object", "properties": {
                        "id": {"type": "string"}, "label": {"type": "string"},
                        "notation": {"type": "string"},
                    }, "required": ["label"], "additionalProperties": False},
                },
                "synthesis_type": {"type": "string", "enum": [
                    "additive_objective", "comparison", "decision_gate", "causal_merge",
                    "evidence_convergence", "reported_endpoint", "proof_implication",
                ]},
                "readout_type": {"type": "string", "enum": [
                    "comparison", "decision_gate", "evidence_convergence",
                    "reported_endpoint", "proof_implication",
                ]},
                "runtime_type": {"type": "string", "enum": [
                    "additive_objective", "comparison", "decision_gate", "causal_merge",
                    "evidence_convergence", "reported_endpoint", "proof_implication",
                ]},
                "output_label": {"type": "string"},
                "semantic_cues": {
                    "type": "array", "minItems": 1, "maxItems": 2,
                    "items": {"type": "string"},
                },
            }, "required": [
                "id", "region_id", "public_label", "role", "visual_form",
                "semantic_cues",
            ],
               "additionalProperties": False,
        }},
        "reading_order": {"type": "array", "items": {"type": "string"}},
        "flows": {"type": "array", "minItems": 4, "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "from": {"type": "string"},
                "to": {"type": "string"},
                "kind": {"type": "string", "enum": list(FLOW_KIND_VALUES)},
                "label": {"type": "string"},
            }, "required": ["id", "from", "to", "kind", "label"],
               "additionalProperties": False,
        }},
    }, "required": ["schema", "primitives", "reading_order", "flows"],
       "additionalProperties": False,
}
TOOL_SPECS: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    (
        "Read",
        "Read a file's content",
        {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]},
        "file_read",
    ),
    (
        "Write",
        "Write content to a file (create or overwrite)",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        "file_write",
    ),
    (
        "WritePart",
        "Store one bounded section for deterministic document assembly",
        {"type": "object", "properties": {"target_path": {"type": "string"}, "part_id": {"type": "string"}, "content": {"type": "string"}}, "required": ["target_path", "part_id", "content"]},
        "write_document_part",
    ),
    (
        "AssembleDocument",
        "Atomically assemble ordered document parts into the canonical target",
        {"type": "object", "properties": {"target_path": {"type": "string"}, "part_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["target_path", "part_ids"]},
        "assemble_document",
    ),
    (
        "Edit",
        "Replace specific text in a file",
        {"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "pattern": "\\S"}, "old_text": {"type": "string", "minLength": 1}, "new_text": {"type": "string", "description": "Replacement text; empty string deletes the exact match"}}, "required": ["path", "old_text", "new_text"]},
        "file_edit",
    ),
    (
        "Glob",
        "List files in a directory",
        {"type": "object", "properties": {"directory": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["directory"]},
        "file_list",
    ),
    (
        "Grep",
        "Find matching file paths. pattern is a filename glob (such as *.md); content_query is a case-insensitive literal substring, not a regular expression. Search alternatives in separate calls; use Read for matching lines.",
        {"type": "object", "properties": {"directory": {"type": "string"}, "pattern": {"type": "string", "description": "Filename glob, not a content regex"}, "content_query": {"type": "string", "description": "Literal substring; |, brackets and backslashes are matched literally"}}, "required": ["directory", "pattern"]},
        "file_search",
    ),
    (
        "Bash",
        "Execute a shell command",
        {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]},
        "terminal_exec",
    ),
    (
        "ssh_exec",
        "Execute command on remote SSH server",
        {"type": "object", "properties": {"server_id": {"type": "string"}, "command": {"type": "string"}}, "required": ["server_id", "command"]},
        "ssh_exec",
    ),
    (
        "ssh_deploy",
        "Deploy experiment on remote GPU server",
        {"type": "object", "properties": {"server_id": {"type": "string"}, "script_path": {"type": "string"}, "args": {"type": "string"}, "gpu_id": {"type": "integer"}}, "required": ["server_id", "script_path"]},
        "ssh_deploy_experiment",
    ),
    (
        "ssh_sync",
        "Sync local directory to remote server (rsync/scp). Use before running remote experiments.",
        {"type": "object", "properties": {"server_id": {"type": "string"}, "local_dir": {"type": "string"}, "remote_dir": {"type": "string"}}, "required": ["server_id", "local_dir"]},
        "ssh_sync",
    ),
    (
        "arxiv_search",
        "Search academic papers on arXiv",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "arxiv_search",
    ),
    (
        "openalex_search",
        "Search academic works and citation metadata on OpenAlex",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "openalex_search",
    ),
    (
        "pubmed_search",
        "Search biomedical literature on PubMed",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "pubmed_search",
    ),
    (
        "WebSearch",
        "Search the web for information",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "web_search",
    ),
    (
        "WebFetch",
        "Fetch a URL and return its text content",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        "web_fetch",
    ),
    (
        "latex_compile",
        "Compile a LaTeX project to PDF",
        {"type": "object", "properties": {"project_dir": {"type": "string"}, "main_tex": {"type": "string"}}, "required": ["project_dir"]},
        "latex_compile",
    ),
    (
        "gpu_status",
        "Check GPU status on remote server",
        {"type": "object", "properties": {"server_id": {"type": "string"}}, "required": ["server_id"]},
        "gpu_status",
    ),
    (
        "semantic_scholar_search",
        "Search academic papers on Semantic Scholar (with citation counts)",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "semantic_scholar_search",
    ),
    (
        "verify_citation",
        "Verify if a citation exists in CrossRef/DBLP databases",
        {"type": "object", "properties": {"title": {"type": "string"}, "authors": {"type": "string"}, "year": {"type": "string"}}, "required": ["title"]},
        "verify_citation",
    ),
    (
        "audit_verdict",
        "Record an audit layer verdict (PASS/WARN/FAIL/BLOCKED/ERROR)",
        {"type": "object", "properties": {"project_path": {"type": "string"}, "layer": {"type": "string"}, "verdict": {"type": "string"}, "details": {"type": "string"}}, "required": ["project_path", "layer", "verdict"]},
        "audit_verdict",
    ),
    (
        "audit_status",
        "Read current audit state for the project",
        {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]},
        "audit_status",
    ),
    (
        "wiki_read",
        "Read Research Wiki entries (persistent knowledge base)",
        {"type": "object", "properties": {"project_path": {"type": "string"}, "key": {"type": "string"}}, "required": ["project_path"]},
        "wiki_read",
    ),
    (
        "wiki_write",
        "Write/update a Research Wiki entry",
        {"type": "object", "properties": {"project_path": {"type": "string"}, "key": {"type": "string"}, "content": {"type": "string"}}, "required": ["project_path", "key", "content"]},
        "wiki_write",
    ),
    (
        "patent_search",
        "Search patents (Google Patents / Espacenet)",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "patent_search",
    ),
    (
        "patent_prior_art",
        "Analyze prior art for a given invention",
        {"type": "object", "properties": {"invention_description": {"type": "string"}, "claims": {"type": "array", "items": {"type": "string"}}}, "required": ["invention_description"]},
        "patent_prior_art",
    ),
    (
        "patent_claims_template",
        "Generate patent claims template from key components",
        {"type": "object", "properties": {"title": {"type": "string"}, "components": {"type": "array", "items": {"type": "string"}}, "method_steps": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "components", "method_steps"]},
        "patent_claims_template",
    ),
    (
        "meta_optimize_propose",
        "Propose a skill prompt modification (self-improvement)",
        {"type": "object", "properties": {"project_path": {"type": "string"}, "skill_name": {"type": "string"}, "original_content": {"type": "string"}, "proposed_content": {"type": "string"}, "description": {"type": "string"}}, "required": ["project_path", "skill_name", "original_content", "proposed_content", "description"]},
        "meta_optimize_propose",
    ),
    (
        "begin_figure_storyboard",
        "Start a three-candidate scientific layout competition for one figure.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"]},
        "begin_figure_storyboard",
    ),
    (
        "add_figure_storyboard_candidate",
        "Append exactly one validated scientific layout candidate; call three times before selection.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "candidate": STORYBOARD_CANDIDATE_SCHEMA,
        }, "required": ["artifact_name", "candidate"]},
        "add_figure_storyboard_candidate",
    ),
    (
        "select_figure_storyboard",
        "Select one of the three previously submitted layouts for one figure.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "selected_id": {"type": "string"},
            "selection_reason": {"type": "string"},
        }, "required": ["artifact_name", "selected_id", "selection_reason"]},
        "select_figure_storyboard",
    ),
    (
        "submit_figure_storyboard",
        "Compatibility wrapper for local callers; workflow agents should use begin/add/select to keep calls small.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "candidates": {"type": "array", "minItems": 3, "maxItems": 3,
                           "items": STORYBOARD_CANDIDATE_SCHEMA},
            "selected_id": {"type": "string"},
            "selection_reason": {"type": "string"},
        }, "required": ["artifact_name", "candidates", "selected_id", "selection_reason"]},
        "submit_figure_storyboard",
    ),
    (
        "prepare_model_svg_draft",
        "Load the source-bound scientific brief for a model-owned full SVG composition.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"], "additionalProperties": False},
        "prepare_model_svg_draft",
    ),
    (
        "submit_model_svg_draft",
        "Validate and stage one complete model-owned SVG, including its text, arrows, and layout.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "svg_source": {"type": "string"},
            "visual_blueprint": VISUAL_BLUEPRINT_TOOL_SCHEMA,
            "element_mappings": ELEMENT_MAPPING_TOOL_SCHEMA,
        }, "required": [
            "artifact_name", "svg_source", "visual_blueprint", "element_mappings",
        ],
           "additionalProperties": False},
        "submit_model_svg_draft",
    ),
    (
        "begin_figure_svg_draft",
        "Start a fresh staged SVG with root, definitions, styles, and canvas. Use before semantic fragments.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "opening_svg": {"type": "string"},
        }, "required": ["artifact_name", "opening_svg"]},
        "begin_figure_svg_draft",
    ),
    (
        "prepare_figure_svg_canvas",
        "Prepare deterministic object boxes and scientific routes from a typed mechanism IR.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "mechanism_ir": MECHANISM_IR_TOOL_SCHEMA,
        }, "required": ["artifact_name", "mechanism_ir"], "additionalProperties": False},
        "prepare_figure_svg_canvas",
    ),
    (
        "append_figure_canvas_primitive",
        "Draw one text-free domain glyph inside a runtime-owned scientific object box.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"}, "primitive_id": {"type": "string"},
            "primitive_svg": {"type": "string"},
        }, "required": ["artifact_name", "primitive_id", "primitive_svg"],
           "additionalProperties": False},
        "append_figure_canvas_primitive",
    ),
    (
        "replace_figure_canvas_primitive",
        "Replace one text-free glyph while preserving object boxes, labels, and relations.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"}, "primitive_id": {"type": "string"},
            "primitive_svg": {"type": "string"},
        }, "required": ["artifact_name", "primitive_id", "primitive_svg"],
           "additionalProperties": False},
        "replace_figure_canvas_primitive",
    ),
    (
        "finalize_figure_svg_canvas",
        "Assemble the hybrid SVG only after every selected storyboard region exists.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"], "additionalProperties": False},
        "finalize_figure_svg_canvas",
    ),
    (
        "refresh_figure_canvas_runtime",
        "Refresh runtime-owned labels and routes without regenerating scientific glyphs.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"], "additionalProperties": False},
        "refresh_figure_canvas_runtime",
    ),
    (
        "append_figure_svg_fragment",
        "Append one model-authored semantic SVG layer or mechanism group to the active figure draft.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "fragment_id": {"type": "string"},
            "svg_fragment": {"type": "string"},
        }, "required": ["artifact_name", "fragment_id", "svg_fragment"]},
        "append_figure_svg_fragment",
    ),
    (
        "draft_print_diagnostics",
        "List exact too-small SVG text and owning fragment before submission; no model call.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"]},
        "draft_print_diagnostics",
    ),
    (
        "review_figure_svg_draft",
        "Render the current SVG draft and obtain image-based critique focused on one fragment before final assembly.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "focus_fragment": {"type": "string"},
            "review_question": {"type": "string"},
        }, "required": ["artifact_name", "focus_fragment", "review_question"]},
        "review_figure_svg_draft",
    ),
    (
        "review_figure_svg_composition",
        "Review the complete rendered SVG against the final native-image contract before formal submission.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "visual_blueprint": VISUAL_BLUEPRINT_TOOL_SCHEMA,
        }, "required": ["artifact_name", "visual_blueprint"],
         "additionalProperties": False},
        "review_figure_svg_composition",
    ),
    (
        "replace_figure_svg_fragment",
        "Replace one named SVG semantic layer while preserving all other reviewed fragments.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
            "fragment_id": {"type": "string"},
            "svg_fragment": {"type": "string"},
        }, "required": ["artifact_name", "fragment_id", "svg_fragment"]},
        "replace_figure_svg_fragment",
    ),
    (
        "finalize_figure_svg_draft",
        "Assemble and XML-validate the staged model-authored SVG, returning source_path for generate_figure.",
        {"type": "object", "properties": {
            "artifact_name": {"type": "string"},
        }, "required": ["artifact_name"]},
        "finalize_figure_svg_draft",
    ),
    (
        "generate_figure",
        "Generate an academic figure. Rich SVG, FigureSpec, Mermaid, Draw.io, and Matplotlib require complete project-grounded source; prose-only template guessing is rejected.",
        {"type": "object", "properties": {
                    "description": {"type": "string", "description": "What the figure should show"},
                    "artifact_name": {"type": "string", "description": "Stable meaningful snake_case filename/FIGURE_SPECS id, e.g. method_architecture"},
                    "figure_type": {"type": "string", "description": "matplotlib | rich_svg | figurespec | mermaid | tikz | gpt_image | nano_banana | drawio | excalidraw"},
                    "output_dir": {"type": "string", "description": "Output directory (default: ./figures/plots)"},
                    "code": {"type": "string", "description": "Complete project-grounded Python plotting script / raw rich SVG / FigureSpec JSON / Mermaid syntax / Draw.io XML / Excalidraw scene JSON. Required for code-native figure types."},
                    "source_path": {"type": "string", "description": "Project-relative finalized SVG draft path; rich_svg accepts this instead of inline code."},
                    "image_size": {"type": "string", "description": "Generated-image size, e.g. 1024x1024"},
                    "image_quality": {"type": "string", "description": "Generated-image quality: low | medium | high"},
                    "scientific_role": {"type": "string", "description": "method | protocol | result | ablation | robustness | analysis | qualitative"},
                    "claim_ids": {"type": "array", "items": {"type": "string"}, "description": "Claim identifiers supported or explained by this figure"},
                    "source_data": {"type": "array", "items": {"type": "string"}, "description": "Project-relative raw data/result files used by the figure"},
                    "caption": {"type": "string", "description": "Publication caption stating what is shown and why it matters"},
                    "scientific_question": {"type": "string", "description": "Research question answered or clarified by this figure"},
                    "intended_comparison": {"type": "string", "description": "Methods, mechanisms, or conditions compared by the visual"},
                    "visual_encoding": {"type": "string", "description": "How variables, mechanisms, or comparisons are encoded"},
                    "uncertainty_encoding": {"type": "string", "description": "Confidence interval/error encoding, or not_applicable for method diagrams"},
                    "evidence_status": {"type": "string", "description": "executed | implemented_design | planned_design | qualitative"},
                    "manuscript_section": {"type": "string", "description": "Target paper section, e.g. Method or Results"},
                    "label": {"type": "string", "description": "Stable LaTeX label declared by the asset plan, e.g. fig:main-comparison"},
                    "data_path": {"type": "string", "description": "Project-relative derived plotting table when applicable"},
                    "code_symbols": {"type": "array", "items": {"type": "string"}, "description": "Real classes/functions/config symbols represented in the scene"},
                    "source_artifacts": {"type": "array", "items": {"type": "string"}, "description": "Project files read to design the scene"},
                    "element_mappings": FIGURE_ELEMENT_MAPPINGS_TOOL_SCHEMA,
                    "visual_blueprint": VISUAL_BLUEPRINT_TOOL_SCHEMA,
                    "recommended_backend": {"type": "string", "description": "Backend copied from FIGURE_SPECS: matplotlib | rich_svg | figurespec | mermaid | tikz | gpt_image | nano_banana | drawio | excalidraw"},
                    "recommended_skill": {"type": "string", "description": "Skill copied from FIGURE_SPECS; runtime verifies the actual invoking skill"},
                    "figure_budget": {"type": "integer", "minimum": 2, "maximum": 12, "description": "Maximum distinct semantic figures for this project (default 6)"},
                }, "required": ["description"]},
        "generate_figure",
    ),
    (
        "figure_manifest",
        "List persisted figure assets, editable sources, paper-ready outputs, hashes, and captions.",
        {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]},
        "figure_manifest",
    ),
    (
        "scaffold_paper",
        "Create a new paper project from a venue template",
        {"type": "object", "properties": {"project_dir": {"type": "string"}, "venue": {"type": "string"}, "title": {"type": "string"}, "author": {"type": "string"}, "affiliation": {"type": "string"}}, "required": ["project_dir", "venue"]},
        "scaffold_paper_tool",
    ),
    (
        "overleaf_sync",
        "Sync local project with Overleaf (pull/push/sync)",
        {"type": "object", "properties": {"action": {"type": "string", "enum": ["pull", "push", "sync"]}, "project_id": {"type": "string"}}, "required": ["action", "project_id"]},
        "overleaf_sync_tool",
    ),
    (
        "Agent",
        "Spawn a sub-agent to execute a task in parallel. Returns the result when done.",
        {"type": "object", "properties": {"prompt": {"type": "string", "description": "Task description for the sub-agent"}, "tools": {"type": "string", "description": "Comma-separated tool names to restrict"}}, "required": ["prompt"]},
        "spawn_agent",
    ),
    (
        "Skill",
        "Invoke another MERAK skill by name (e.g. /research-lit, /novelty-check)",
        {"type": "object", "properties": {"skill_name": {"type": "string", "description": "Skill name with / prefix"}, "arguments": {"type": "string", "description": "Arguments to pass to the skill"}}, "required": ["skill_name"]},
        "invoke_skill",
    ),
    (
        "reviewer_api",
        "Run a fresh, isolated ModelRole.REVIEWER API request. Prefer file_path for a review of frozen primary artifacts.",
        {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Artifact content to review"},
                        "prompt": {"type": "string", "description": "Reviewer API request or instructions"},
                        "reviewer_prompt": {"type": "string", "description": "Custom reviewer system prompt"},
                        "file_path": {"type": "string", "description": "Path to an artifact for a cold review"},
                        "config": {"type": "object", "description": "Optional reviewer reasoning configuration"},
                        "model": {"type": "string", "description": "Optional requested reviewer model; configured reviewer routing remains authoritative"},
                    },
                    "required": [],
                    "anyOf": [
                        {"required": ["content"]},
                        {"required": ["prompt"]},
                        {"required": ["file_path"]},
                    ],
                },
        "cross_model_review",
    ),
    (
        "AskUserQuestion",
        "Ask the user a question and wait for their answer. In auto-proceed mode, selects the first option.",
        {"type": "object", "properties": {"question": {"type": "string"}, "options": {"type": "string", "description": "Comma-separated options"}}, "required": ["question"]},
        "ask_user_question",
    ),
    (
        "reviewer_api_reply",
        "Continue an isolated reviewer-model API session using its durable thread ID",
        {"type": "object", "properties": {"thread_id": {"type": "string", "description": "Session ID from the previous reviewer API call"}, "message": {"type": "string", "description": "Follow-up message (e.g. revised content for re-review)"}}, "required": ["thread_id", "message"]},
        "cross_model_review_reply",
    ),
    (
        "mcp__gemini-cli__search",
        "Search using Gemini with Google Search grounding. Falls back to WebSearch if Gemini unavailable.",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
        "gemini_search",
    ),
    (
        "mcp__zotero__search",
        "Search the user's Zotero reference library",
        {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
        "zotero_search",
    ),
    (
        "mcp__obsidian-vault__read",
        "Read or search the user's Obsidian vault notes",
        {"type": "object", "properties": {"vault_path": {"type": "string"}, "query": {"type": "string"}}, "required": []},
        "obsidian_read",
    ),
    (
        "threat_scan",
        "Scan content for prompt injection / malicious code patterns",
        {"type": "object", "properties": {"content": {"type": "string"}, "scope": {"type": "string", "enum": ["all", "context", "strict"]}}, "required": ["content"]},
        "threat_scan",
    ),
    (
        "evidence_check",
        "Verify a claim's cited evidence exists (file + value presence check)",
        {"type": "object", "properties": {"claim": {"type": "string"}, "source_path": {"type": "string"}, "cited_value": {"type": "string"}}, "required": ["claim", "source_path"]},
        "evidence_check",
    ),
    (
        "provenance_stamp",
        "Record provenance (author + reviewer model) for an artifact file",
        {"type": "object", "properties": {"artifact_path": {"type": "string"}, "author_model": {"type": "string"}, "reviewer_model": {"type": "string"}, "verdict": {"type": "string"}}, "required": ["artifact_path", "author_model"]},
        "provenance_stamp",
    ),
    (
        "extract_paper_style",
        "Extract structural style profile from a reference paper (section ordering, density, format)",
        {"type": "object", "properties": {"source_path": {"type": "string"}}, "required": ["source_path"]},
        "extract_paper_style",
    ),
    (
        "watchdog_check",
        "Check if remote experiment processes are still alive (screen sessions + GPU utilization)",
        {"type": "object", "properties": {"server_id": {"type": "string"}, "session_prefix": {"type": "string"}}, "required": ["server_id"]},
        "watchdog_check",
    ),
)


def register_tool_specs(engine: Any, handlers: Mapping[str, Any]) -> None:
    for name, description, schema, handler_name in TOOL_SPECS:
        handler = handlers.get(handler_name)
        if handler is None:
            raise RuntimeError(f"Tool handler is unavailable: {handler_name}")
        engine.register_tool(name, description, schema, handler)
