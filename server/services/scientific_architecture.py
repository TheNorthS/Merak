"""Compile source-grounded scientific architecture semantics for figure adapters.

Method contracts and implementation evidence define the graph; the renderer
selects geometry without inventing a different scientific mechanism."""

from __future__ import annotations

from typing import Any

from .scientific_architecture_grammar import ArchitectureGrammar
from .scientific_architecture_models import ArchitectureCompilation
from .scientific_architecture_benchmark import compile_benchmark_model_suite
from .scientific_architecture_factorized import compile_factorized_representation_story
from .scientific_architecture_mechanism import compile_mechanism_story
from .scientific_architecture_generic import compile_architecture


class ScientificArchitectureCompiler(ArchitectureGrammar):
    """Compile a source-grounded model blueprint into a publication scene.

    The compiler owns visual grammar and geometry.  The language model owns
    neither node placement nor the decision to duplicate a module.  This keeps
    architecture figures faithful to implementation evidence while allowing a
    richer vocabulary than generic rounded rectangles.
    """

    @classmethod
    def _compile_factorized_representation_story(
        cls,
        asset: dict[str, Any],
        components: list[dict[str, Any]],
        family: str,
        mechanisms: list[dict[str, Any]],
    ) -> ArchitectureCompilation:
        return compile_factorized_representation_story(
            cls, asset, components, family, mechanisms,
        )

    @classmethod
    def _compile_benchmark_model_suite(
        cls,
        asset: dict[str, Any],
        components: list[dict[str, Any]],
        family: str,
    ) -> ArchitectureCompilation:
        return compile_benchmark_model_suite(cls, asset, components, family)

    @classmethod
    def _compile_mechanism_story(
        cls,
        asset: dict[str, Any],
        components: list[dict[str, Any]],
        family: str,
    ) -> ArchitectureCompilation:
        return compile_mechanism_story(cls, asset, components, family)

    @classmethod
    def compile(cls, asset: dict[str, Any]) -> ArchitectureCompilation:
        return compile_architecture(cls, asset)


scientific_architecture_compiler = ScientificArchitectureCompiler()
