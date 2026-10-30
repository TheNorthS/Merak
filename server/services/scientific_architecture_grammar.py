"""Reusable visual grammar for source-grounded scientific architectures."""

from __future__ import annotations

from typing import Any, Iterable
import re


class ArchitectureGrammar:
    _PALETTE = {
        "data": ("#E8F1FB", "#2563EB"),
        "representation": ("#EAF7F4", "#0F766E"),
        "conditioning": ("#F3ECFC", "#7C3AED"),
        "objective": ("#FFF3E3", "#D97706"),
        "evaluation": ("#FDECF2", "#BE123C"),
        "neutral": ("#F8FAFC", "#64748B"),
    }

    _PREDICTIVE_TERMS = (
        "accuracy", "auroc", "auc", "f1", "classification", "classifier", "predictive",
        "prediction", "predictor", "logits", "regression", "rmse", "mae",
        "calibration", "brier", "ece",
    )

    @classmethod
    def _architecture_family(
        cls,
        asset: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> str:
        """Infer visual grammar without forcing every method into an ML diagram."""
        brief = dict(asset.get("method_brief") or {})
        declared = cls._text(
            brief.get("study_archetype")
            or brief.get("research_family")
            or asset.get("study_archetype")
        ).casefold()
        text = " ".join((
            declared,
            cls._text(brief.get("title")),
            cls._text(brief.get("problem")),
            " ".join(cls._component_text(item) for item in components),
        )).casefold()
        if any(term in declared for term in ("formal", "theory", "proof")):
            return "formal_reasoning"
        if any(term in declared for term in ("qualitative", "humanities", "mixed")):
            return "qualitative_inquiry"
        if any(term in declared for term in ("trial", "clinical", "cohort", "diagnostic", "prognostic")):
            return "clinical_study"
        if any(term in declared for term in ("omics", "assay", "controlled_experiment")) or any(
            term in text for term in ("assay", "specimen", "reagent", "microscopy", "sequencing")
        ):
            return "experimental_protocol"
        if any(term in declared for term in ("systems", "testbed", "simulation_modeling")):
            return "systems_pipeline"
        endpoints = " ".join(
            cls._text(value)
            for value in (
                brief.get("reported_endpoints")
                or brief.get("endpoints")
                or []
            )
        ).casefold()
        if any(term in endpoints or term in text for term in cls._PREDICTIVE_TERMS):
            return "predictive_model"
        return "computational_method"

    @classmethod
    def _profile_labels(cls, family: str) -> dict[str, str]:
        profiles = {
            "predictive_model": {
                "method": "SHARED REPRESENTATION MODEL",
                "objectives": "TRAINING OBJECTIVES",
                "evaluation": "HELD-OUT EVALUATION",
                "output": "Held-out predictions",
                "flow": "tensor flow",
            },
            "clinical_study": {
                "method": "STUDY & ANALYSIS PATH",
                "objectives": "INTERVENTIONS / ESTIMANDS",
                "evaluation": "OUTCOMES & VALIDATION",
                "output": "Study outcomes",
                "flow": "analysis flow",
            },
            "experimental_protocol": {
                "method": "EXPERIMENTAL WORKFLOW",
                "objectives": "PERTURBATIONS / ASSAYS",
                "evaluation": "MEASUREMENTS & VALIDATION",
                "output": "Measured endpoints",
                "flow": "sample flow",
            },
            "systems_pipeline": {
                "method": "SYSTEM / SIMULATION PIPELINE",
                "objectives": "WORKLOADS & CONTROLS",
                "evaluation": "SYSTEM RESPONSES",
                "output": "System responses",
                "flow": "process flow",
            },
            "formal_reasoning": {
                "method": "DEFINITIONS & DERIVATION",
                "objectives": "ASSUMPTIONS / CLAIMS",
                "evaluation": "BOUNDARIES & CHECKS",
                "output": "Derived results",
                "flow": "logical dependency",
            },
            "qualitative_inquiry": {
                "method": "SAMPLING & ANALYSIS",
                "objectives": "CODING / INTERPRETATION",
                "evaluation": "TRIANGULATION",
                "output": "Themes and evidence",
                "flow": "evidence flow",
            },
            "computational_method": {
                "method": "COMPUTATIONAL METHOD",
                "objectives": "OBJECTIVES / CONSTRAINTS",
                "evaluation": "OUTPUTS & CHECKS",
                "output": "Analysis outputs",
                "flow": "process flow",
            },
        }
        return profiles.get(family, profiles["computational_method"])

    @staticmethod
    def _text(value: Any, fallback: str = "") -> str:
        return " ".join(str(value or fallback).replace("_", " ").split()).strip()

    @classmethod
    def _short_label(cls, component: dict[str, Any]) -> str:
        label = cls._text(
            component.get("display_name")
            or component.get("label")
            or component.get("source_symbol")
        )
        substitutions = {
            "adaptive avg pool1d": "Global pooling",
            "reconstructionhead": "Reconstruction head",
            "objective model": "Objective wrapper",
            "load manifest": "Data manifest",
            "grouped split": "Group-disjoint split",
            "topology mask": "Topology mask",
            "stem": "Temporal stem",
            "blocks": "Residual blocks",
            "pool": "Global pooling",
            "projection": "Projection head",
            "decoder": "Reconstruction head",
            "temporal nt xent": "Temporal NT-Xent",
            "splitaudit": "Leakage audit",
        }
        return substitutions.get(label.casefold(), label or "Model component")[:54]

    @classmethod
    def _component_text(cls, component: dict[str, Any]) -> str:
        return " ".join((
            cls._text(component.get("label")),
            cls._text(component.get("source_symbol")),
            cls._text(component.get("operation")),
        )).casefold()

    @classmethod
    def _visual_kind(cls, component: dict[str, Any]) -> str:
        lane = str(component.get("lane") or "").casefold()
        identity = " ".join((
            cls._text(component.get("label")),
            cls._text(component.get("source_symbol")),
        )).casefold()
        text = cls._component_text(component)
        if any(term in identity for term in ("split", "sampler", "dataset", "loader")):
            return "database"
        if any(term in identity for term in ("decoder", "reconstruct")):
            return "decoder"
        if any(term in identity for term in ("pool", "aggregate", "reduce")):
            return "pooling"
        if any(term in identity for term in ("projection", "embedding", "latent")):
            return "embedding"
        if any(term in identity for term in (
            "loss", "objective", "xent", "contrastive", "criterion",
        )):
            return "loss"
        if any(term in identity for term in (
            "classifier", "task head", "prediction head", "predictor", "logits",
        )):
            return "head"
        if any(term in identity for term in ("conv", "stem", "patch", "tokenizer")):
            return "tensor_stack"
        if any(term in identity for term in (
            "block", "encoder", "transformer", "attention", "mixer", "backbone",
        )):
            return "module_stack"
        if any(term in identity for term in ("adjacency", "topology", "mask", "matrix")):
            return "matrix"
        if any(term in identity for term in ("manifest", "signal", "waveform", "input")):
            return "signal"
        if lane == "data_and_sampling" and any(
            term in text for term in ("adjacency", "topology", "mask", "matrix")
        ):
            return "matrix"
        if lane == "data_and_sampling":
            return "database"
        if lane == "evaluation":
            return "metric_card"
        if lane == "diagnostics_and_accounting":
            return "audit"
        return "module"

    @classmethod
    def _sublabel(cls, component: dict[str, Any]) -> str:
        operation = cls._text(component.get("operation"))
        source_symbol = cls._text(component.get("source_symbol"))
        identity = " ".join((
            cls._text(component.get("label")), source_symbol,
        )).casefold()
        normalized = f"{source_symbol} {operation}".casefold()
        if "manifest" in identity:
            return "signal · label · group metadata"
        if "split" in identity:
            return "disjoint train · validation · test"
        if any(term in identity for term in ("mask", "topology", "adjacency")):
            return "topology-conditioned channel selection"
        if any(term in identity for term in ("task head", "classifier", "predictor")):
            return "linear probe · fine-tuning · calibration"
        if "conv1d" in normalized:
            if "modulelist" in normalized or "blocks" in normalized:
                return "repeated temporal Conv1D blocks"
            return "Conv1D · activation · dropout"
        if "adaptiveavgpool" in normalized or "global pooling" in normalized:
            return "global temporal reduction"
        if "projection" in normalized or "embedding" in normalized:
            return "linear map to latent embedding"
        if "decoder" in normalized or "reconstruct" in normalized:
            return "latent-to-input reconstruction"
        if any(term in normalized for term in ("xent", "contrastive", "criterion")):
            return "matched objective on paired views"
        if "transformerencoder" in normalized or "multiheadattention" in normalized:
            return "stacked contextual attention blocks"
        if "linear" in normalized:
            return "learned feature projection"
        if "modulelist" in normalized or "sequential" in normalized:
            return "stacked trainable processing blocks"
        if any(term in normalized for term in ("dropout", "layernorm", "batchnorm")):
            return "regularized feature transformation"
        if operation and operation.casefold() not in {
            "declared implementation component", "contains", "uses shared module",
        }:
            # Human-authored implementation-check descriptions may be useful
            # scientific prose. AST expressions, dotted symbols and argument
            # lists are provenance, not publication text.
            looks_like_code = bool(
                re.search(r"[()=\[\]{}]|\b(?:self|nn|torch)\.", operation)
                or re.search(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", operation)
            )
            if not looks_like_code:
                return operation[:42]
        return "registered trainable transformation"

    @staticmethod
    def _dedupe(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @classmethod
    def _source_mapping(
        cls,
        node_id: str,
        component: dict[str, Any] | None,
        *,
        fallback_path: str = "experiments/METHOD_CONTRACT.json",
        semantic_role: str = "architecture evidence",
    ) -> dict[str, str]:
        component = component or {}
        mapping = {
            "element_id": node_id,
            "source_path": str(component.get("source_path") or fallback_path),
            "semantic_role": semantic_role,
        }
        symbol = str(component.get("source_symbol") or "").strip()
        if symbol and mapping["source_path"].casefold().endswith(".py"):
            mapping["source_symbol"] = symbol
        return mapping

    @classmethod
    def _node(
        cls,
        component: dict[str, Any],
        *,
        x: float,
        y: float,
        width: float = 190,
        height: float = 92,
        node_id: str | None = None,
        label: str | None = None,
        sublabel: str | None = None,
        visual_kind: str | None = None,
        palette_role: str | None = None,
    ) -> dict[str, Any]:
        lane = str(component.get("lane") or "").casefold()
        role = palette_role or (
            "data" if lane == "data_and_sampling"
            else "representation" if lane == "representation_model"
            else "objective" if lane == "training_objective"
            else "evaluation" if lane == "evaluation"
            else "neutral"
        )
        fill, stroke = cls._PALETTE[role]
        return {
            "id": node_id or str(component.get("id") or "component"),
            "label": label or cls._short_label(component),
            "sublabel": sublabel if sublabel is not None else cls._sublabel(component),
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "shape": "rounded",
            "visual_kind": visual_kind or cls._visual_kind(component),
            "fill": fill,
            "stroke": stroke,
            "font_size": 15,
        }

