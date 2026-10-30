"""Semantic routing and single-producer ownership for publication figures.

Conceptual figures default to a source-grounded FigureSpec and deterministic
layout. A complete model-authored SVG remains an explicit opt-in strategy.
Quantitative plots and standard protocols retain their distinct producers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SUPPORTED_FIGURE_BACKENDS = {
    "matplotlib",
    "rich_svg",
    "figurespec",
    "excalidraw",
    "drawio",
    "mermaid",
    "tikz",
    "gpt_image",
    "nano_banana",
}

BACKEND_SKILLS = {
    "matplotlib": "paper-figure",
    "rich_svg": "rich-svg-figure",
    "figurespec": "figure-spec",
    "excalidraw": "excalidraw-skill",
    "drawio": "figure-spec",
    "mermaid": "mermaid-diagram",
    "tikz": "paper-figure",
    "gpt_image": "paper-illustration",
    "nano_banana": "paper-illustration",
}

BACKEND_SOURCE_EXTENSIONS = {
    "matplotlib": [".py"],
    "rich_svg": [".svg"],
    "figurespec": [".json"],
    "excalidraw": [".excalidraw"],
    "drawio": [".drawio", ".dio"],
    "mermaid": [".mmd", ".mermaid"],
    "tikz": [".tex"],
    "gpt_image": [".prompt.json", ".json"],
    "nano_banana": [".prompt.json", ".json"],
}

BACKEND_PAPER_FORMATS = {
    "matplotlib": ["pdf", "svg"],
    "rich_svg": ["svg", "pdf"],
    "figurespec": ["svg", "pdf"],
    "excalidraw": ["pdf", "svg"],
    "drawio": ["pdf", "svg", "png"],
    "mermaid": ["svg", "pdf", "png"],
    "tikz": ["pdf"],
    "gpt_image": ["png"],
    "nano_banana": ["png"],
}

QUANTITATIVE_ROLES = {
    "result",
    "main comparison",
    "ablation",
    "robustness",
    "calibration",
    "analysis",
}

FIGURE_NATURES = frozenset({
    "conceptual",
    "quantitative",
    "standard_protocol",
    "naturalistic",
})

PRODUCTION_STRATEGIES = frozenset({
    "deterministic_architecture",
    "model_composed_full_svg",
    "deterministic_plot",
    "deterministic_template",
    "model_generated_image",
})

_STRATEGY_BY_NATURE = {
    "conceptual": "deterministic_architecture",
    "quantitative": "deterministic_plot",
    "standard_protocol": "deterministic_template",
    "naturalistic": "model_generated_image",
}

_BACKEND_BY_STRATEGY = {
    "deterministic_architecture": "figurespec",
    "model_composed_full_svg": "rich_svg",
    "deterministic_plot": "matplotlib",
    "deterministic_template": "rich_svg",
    "model_generated_image": "nano_banana",
}

_PRODUCER_BY_STRATEGY = {
    "deterministic_architecture": "deterministic",
    "model_composed_full_svg": "model",
    "deterministic_plot": "deterministic",
    "deterministic_template": "deterministic",
    "model_generated_image": "model",
}

_SKILL_BY_STRATEGY = {
    "deterministic_architecture": "figure-spec",
    "model_composed_full_svg": "model-svg-figure",
    "deterministic_plot": "paper-figure",
    "deterministic_template": "deterministic-figure-template",
    "model_generated_image": "paper-illustration",
}

def _text(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def normalize_illustration_mode(value: Any) -> str:
    """Require the current system-owned routing selector."""
    normalized = str(value or "auto").strip().casefold()
    if normalized != "auto":
        raise ValueError(f"unsupported illustration mode: {normalized}")
    return normalized






@dataclass(frozen=True)
class FigureRouteContext:
    explicit: str
    semantic_id: str
    role: str
    plot_type: str
    visual: str
    kind: str
    phase: str
    illustration_mode: str
    generation_policy: str
    comparative_model_count: int


@dataclass(frozen=True)
class FigureProductionPolicy:
    """One unambiguous authoring contract shared by planner and runtime."""

    figure_nature: str
    production_strategy: str
    producer_kind: str
    composition_owner: str
    full_svg_authority: bool


def _route_context(asset: Mapping[str, Any]) -> FigureRouteContext:
    explicit = _text(
        asset.get("recommended_backend")
        or asset.get("preferred_backend")
        or asset.get("figure_backend")
    ).replace(" ", "_")
    blueprint = asset.get("architecture_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    configuration = blueprint.get("model_configuration")
    configuration = configuration if isinstance(configuration, dict) else {}
    generation_policy = str(asset.get("generation_policy") or "").strip().casefold()
    if generation_policy not in {"generate", "reuse", "skip"}:
        generation_policy = ""
    return FigureRouteContext(
        explicit=explicit,
        semantic_id=_text(asset.get("id") or asset.get("semantic_key")).replace(" ", "_"),
        role=_text(asset.get("scientific_role")),
        plot_type=_text(asset.get("recommended_plot_type")),
        visual=_text(asset.get("visual_encoding")),
        kind=_text(asset.get("kind")),
        phase=_text(asset.get("generation_phase")),
        illustration_mode=normalize_illustration_mode(asset.get("illustration_mode")),
        generation_policy=generation_policy,
        comparative_model_count=len(list(configuration.get("model_suite") or [])),
    )


def _declared_nature(asset: Mapping[str, Any]) -> str:
    declared = _text(asset.get("figure_nature")).replace(" ", "_")
    return declared if declared in FIGURE_NATURES else ""


def figure_nature(asset: Mapping[str, Any]) -> str:
    """Classify one asset without relying on a domain-specific layout template."""
    declared = _declared_nature(asset)
    if declared:
        return declared
    if bool(asset.get("requires_naturalistic_imagery")):
        return "naturalistic"
    context = _route_context(asset)
    if context.role in QUANTITATIVE_ROLES or bool(asset.get("data_path")):
        return "quantitative"
    narrative = _text(asset.get("narrative_level"))
    if (
        context.semantic_id == "evaluation_design"
        or context.role in {"protocol", "evaluation design"}
        or narrative == "study protocol"
    ):
        return "standard_protocol"
    return "conceptual"


def production_policy(asset: Mapping[str, Any]) -> FigureProductionPolicy:
    """Resolve figure nature into an enforceable single-owner policy."""
    nature = figure_nature(asset)
    strategy = _STRATEGY_BY_NATURE[nature]
    declared = str(asset.get("production_strategy") or "").strip().casefold()
    if declared == "model_composed_full_svg" and nature == "conceptual":
        strategy = "model_composed_full_svg"
    elif declared and declared != strategy:
        raise ValueError(
            f"production_strategy={declared} conflicts with figure_nature={nature}"
        )
    producer = _PRODUCER_BY_STRATEGY[strategy]
    model_composed = strategy == "model_composed_full_svg"
    return FigureProductionPolicy(
        figure_nature=nature,
        production_strategy=strategy,
        producer_kind=producer,
        composition_owner="model" if producer == "model" else "runtime",
        full_svg_authority=model_composed,
    )


def _select_backend(
    asset: Mapping[str, Any],
    context: FigureRouteContext,
) -> tuple[str, str, FigureProductionPolicy]:
    policy = production_policy(asset)
    if context.kind and context.kind != "figure":
        return (
            "matplotlib",
            "non-figure fallback; the renderer should normally skip this asset",
            policy,
        )
    if policy.production_strategy == "deterministic_plot":
        return (
            "matplotlib",
            "quantitative evidence is rendered reproducibly from its bound machine-readable data",
            policy,
        )
    if policy.production_strategy == "deterministic_template":
        return (
            "rich_svg",
            "standard reporting protocol uses a deterministic, contract-bound vector template",
            policy,
        )
    if policy.production_strategy == "deterministic_architecture":
        return (
            "figurespec",
            "source-grounded conceptual relations use deterministic vector layout and typography",
            policy,
        )
    if policy.production_strategy == "model_generated_image":
        return (
            "nano_banana",
            "naturalistic content requires a model-generated raster illustration with a persisted prompt contract",
            policy,
        )
    return (
        "rich_svg",
        "conceptual scientific content is composed end-to-end as one model-authored editable SVG",
        policy,
    )


def recommend_figure_route(
    asset: Mapping[str, Any],
    publication_style: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the backend and executable skill for one semantic paper asset."""

    del publication_style  # routing is driven by the asset's semantic role
    context = _route_context(asset)
    backend, reason, policy = _select_backend(asset, context)
    recommended_skill = _SKILL_BY_STRATEGY[policy.production_strategy]
    return {
        "figure_nature": policy.figure_nature,
        "production_strategy": policy.production_strategy,
        "producer_kind": policy.producer_kind,
        "composition_owner": policy.composition_owner,
        "full_svg_authority": policy.full_svg_authority,
        "recommended_backend": backend,
        "recommended_skill": recommended_skill,
        "backend_reason": reason,
        "editable_source_extensions": BACKEND_SOURCE_EXTENSIONS[backend],
        "paper_output_formats": BACKEND_PAPER_FORMATS[backend],
        "preview_format": "png",
        "illustration_mode": (
            context.illustration_mode if context.phase == "phase 2b" else ""
        ),
        # Asset producers may declare a canonical artifact that must be reused.
        # Routing chooses a backend; it must never silently turn reuse into a
        # second generation job (or turn an explicit skip back on).
        "generation_policy": context.generation_policy or "generate",
    }


def expected_source_extensions(backend: str) -> set[str]:
    normalized = _text(backend).replace(" ", "_")
    return set(BACKEND_SOURCE_EXTENSIONS.get(normalized, []))


def manifest_backend_matches(
    expected_backend: str,
    expected_skill: str,
    actual_backend: str,
) -> bool:
    """Match one manifest type exactly."""
    expected = str(expected_backend or "").strip()
    actual = str(actual_backend or "").strip()
    return expected == actual
