"""Native-image review and best-candidate selection for rich SVG figures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .api_visual_review_schemas import RICH_SVG_HARD_CHECKS
from .rich_svg_blueprint import blueprint_minimums


PROTOCOL = "native-image-v1"
QUALITY_TARGET_SCORE = 8.0
REVIEW_POLICY_VERSION = 3
LOCAL_PROTOCOL = "deterministic-local-pixels-v1"
LOCAL_REVIEW_POLICY_VERSION = 1
LOCAL_CHECKS = (
    "svg_xml_and_vector_only_contract", "scientific_detail_density",
    "source_element_mapping", "print_geometry", "raster_legibility",
    "canvas_edge_safety", "contrast_and_visual_differentiation",
)


def is_deterministic_template(metadata: dict[str, Any]) -> bool:
    """Only the verified runtime producer may use the local-review route."""
    return (
        metadata.get("production_strategy") == "deterministic_template"
        and metadata.get("producer_kind") == "deterministic"
        and metadata.get("skill_invocation_verified") is True
        and metadata.get("skill_invocation_verified_by")
        == "deterministic-runtime-figure-builder"
    )


def _local_brief_sha256(metadata: dict[str, Any]) -> str:
    payload = {
        key: metadata.get(key) for key in (
            "producer_input_sha256", "scientific_role", "scientific_question",
            "intended_comparison", "scientific_scene", "scene_contract",
            "source_bindings", "source_data", "element_mappings",
            "production_strategy", "producer_kind", "visual_encoding",
        )
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def local_review_record(
    metadata: dict[str, Any], source: Path, pdf: Path, png: Path,
) -> dict[str, Any]:
    """Attest exact locally checked variants without claiming model independence."""
    if not is_deterministic_template(metadata):
        raise ValueError("local rich-SVG review requires a verified deterministic template")
    return {
        "protocol": LOCAL_PROTOCOL,
        "review_policy_version": LOCAL_REVIEW_POLICY_VERSION,
        "review_backend": "deterministic-runtime-source-and-pixels-v1",
        "status": "passed", "checks": list(LOCAL_CHECKS),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "image_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "brief_sha256": _local_brief_sha256(metadata),
    }


def local_review_issues(
    metadata: dict[str, Any], source: Path, pdf: Path | None,
    preview: Path | None, *, require_round: bool = True,
) -> list[str]:
    """Reject missing, forged-route, or stale local SVG/PDF/PNG evidence."""
    issues: list[str] = []
    if not is_deterministic_template(metadata):
        issues.append("local rich-SVG review requires a verified deterministic template")
    if metadata.get("independent_visual_review"):
        issues.append("deterministic template cannot claim independent native-image review")
    review = metadata.get("deterministic_visual_review")
    review = review if isinstance(review, dict) else {}
    if review.get("protocol") != LOCAL_PROTOCOL:
        return [*issues, "deterministic local-pixel review is missing or invalid"]
    checks = review.get("checks")
    valid_checks = isinstance(checks, list) and all(
        isinstance(item, str) for item in checks
    ) and set(checks) == set(LOCAL_CHECKS)
    if (
        review.get("review_policy_version") != LOCAL_REVIEW_POLICY_VERSION
        or review.get("review_backend") != "deterministic-runtime-source-and-pixels-v1"
        or review.get("status") != "passed"
        or not valid_checks
    ):
        issues.append("deterministic local-pixel review policy or checks are invalid")
    if review.get("brief_sha256") != _local_brief_sha256(metadata):
        issues.append("deterministic local-pixel review is stale for the scientific brief")
    current_hashes: dict[str, str] = {}
    for path, field, label in (
        (source, "source_sha256", "editable SVG"),
        (pdf, "pdf_sha256", "rendered PDF"),
        (preview, "image_sha256", "rendered PNG"),
    ):
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path else ""
        except OSError:
            current = ""
        current_hashes[field] = current
        if not current or review.get(field) != current:
            issues.append(f"deterministic local-pixel review is stale for the {label}")
    if require_round:
        rounds = metadata.get("visual_review_rounds")
        last = rounds[-1] if isinstance(rounds, list) and rounds else {}
        if not isinstance(last, dict) or last.get("status") != "passed":
            issues.append("deterministic local-pixel review lacks a passing round")
        elif (
            last.get("content_sha256") != current_hashes["source_sha256"]
            or last.get("render_sha256") != current_hashes["image_sha256"]
        ):
            issues.append("deterministic local-pixel round is stale for source or pixels")
        if (
            metadata.get("visual_review_policy") == "enhanced_local_pixels_required"
            and isinstance(last, dict)
            and last.get("review_kind") != "enhanced_local_pixels"
        ):
            issues.append("deterministic enhanced local-pixel review is missing")
    return issues


def _minimum_readback_relations(metadata: dict[str, Any]) -> int:
    """Use the authored scene edge count; legacy metadata keeps the old floor."""
    if metadata.get("production_strategy") != "model_composed_full_svg":
        return 3
    return blueprint_minimums(metadata).flows


def _brief_sha256(metadata: dict[str, Any]) -> str:
    scientific_brief = {
        key: metadata.get(key) for key in (
            "scientific_role", "scientific_question", "intended_comparison",
            "scientific_scene", "scene_contract", "source_bindings",
            "visual_blueprint", "design_brief", "production_strategy",
            "probe_configuration",
        )
    }
    encoded = json.dumps(scientific_brief, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prompt(
    artifact_id: str, metadata: dict[str, Any],
    blind_readback: dict[str, Any] | None = None,
) -> str:
    blueprint = metadata.get("visual_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    primitives = [
        f"{item.get('id')}: {item.get('visual_form')} — {item.get('scientific_meaning')}"
        for item in blueprint.get("primitives") or [] if isinstance(item, dict)
    ]
    from .figure_review_findings import (
        review_target_catalog, reviewer_ownership_prompt,
    )

    ownership = reviewer_ownership_prompt(
        review_target_catalog(metadata, artifact_id=artifact_id),
    )
    return f"""Review the attached rendered scientific figure as a strict top-venue visual editor.

Artifact: {artifact_id}
Scientific role: {metadata.get('scientific_role') or artifact_id}
Question: {metadata.get('scientific_question') or ''}
Narrative level: {blueprint.get('narrative_level') or ''}
Focal message: {blueprint.get('focal_message') or ''}
Intended visual primitives: {'; '.join(primitives[:12])}
Formal relation: {blueprint.get('formal_relation') or ''}
Source-bound probe configuration: {json.dumps(metadata.get('probe_configuration') or [], ensure_ascii=False)}
Blind first-reader report: {json.dumps(blind_readback or {}, ensure_ascii=False)}

Use the source-bound probe mode to distinguish design from active computation.
A frozen_downstream probe is trained separately after freezing the encoder and
does not imply gradient reversal into that encoder. An unspecified mode is not
evidence of an active adversarial or joint-loss branch. A planned or conditional
probe may appear if it is explicitly shown as such; do not demand invented
activation, measured probe results, or gradients unsupported by the configuration.

Judge the pixels directly. Highest priority: a researcher understands the core
scientific idea within five seconds, then can recover the detailed mechanism by
following hierarchy and arrows. Reject a diagram that merely names the
intended primitives without depicting their real relations. Mark generic cards,
decorative glyphs, excess whitespace, weak hierarchy, and prose-heavy panels
as advisory unless they obscure the scientific mechanism or paper-scale text.
Unclear branch/merge logic and unreadable content remain blockers.
Reward domain-appropriate scientific primitives, compact composition, distinct
mechanisms, balanced whitespace, precise arrows, restrained color, and polished
paper-scale presentation. Do not demand invented results or a copied template.
Give concise repair instructions that preserve strong parts. Use verdict=accept
when the scientific meaning, causal flow, first reading, paper-scale text, and
visual integrity checks are true and no blocker remains. Score against a
{QUALITY_TARGET_SCORE:.1f} quality target, but treat score and optional polish
(balance, label economy, card treatment, and aesthetics) as advisory, not an
independent veto. Mark wrong scientific relations, obscured causal routes,
clipped or unreadable content as blockers; name cosmetic polish as advisory.
The
blind report is evidence of what the pixels communicated before revealing the
intended method. Do not credit an intended relation that the blind reader could
not recover; explain the visual repair needed to make it independently legible.
Evaluate a paper-level architecture figure at its intended abstraction. Missing
tensor dimensions, coefficient values, acronym expansion, or full operator
definitions are not defects unless the scientific claim specifically depends
on them. Distinguish contextual details from ambiguous causal flow, comparison
sets, eligibility rules, branches, merges, or outputs.
Check active-versus-conditional probe depiction against the source-bound states.
A frozen_downstream probe operates after encoder training and does not require
a joint model head, a GRL path, or a positive joint loss weight. An unspecified
or disabled probe must not be depicted as an established active objective.

{ownership}"""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _archive(
    root: Path, artifact_id: str, digest: str,
    files: tuple[Path, Path, Path], review: dict[str, Any], trace_path: str,
) -> tuple[Path, dict[str, Any]]:
    directory = root / ".merak" / "figure-candidates" / artifact_id / f"{digest[:16]}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    for source in files:
        shutil.copy2(source, directory / source.name)
    atomic_write_json(directory / "review.json", {
        "schema": 1, "protocol": PROTOCOL, "artifact_id": artifact_id,
        "source_sha256": digest, "reviewed_at": time.time(),
        "review": review, "trace_path": trace_path,
    })
    return directory, _load(directory.parent / "best.json")


def review_gate_issues(review: dict[str, Any]) -> list[str]:
    """Separate publication safety from a numerical or cosmetic preference."""
    issues: list[str] = []
    score = review.get("score")
    if (type(score) not in {int, float} or not math.isfinite(score)
            or not 1 <= score <= 10):
        issues.append("native-image figure score is invalid")
    if review.get("verdict") != "accept":
        issues.append("native-image figure review did not accept the candidate")
    checklist = review.get("checklist")
    if not isinstance(checklist, dict) or any(
        checklist.get(key) is not True for key in RICH_SVG_HARD_CHECKS
    ):
        issues.append("native-image scientific or legibility checklist failed")
    findings = review.get("findings")
    if not isinstance(findings, list):
        issues.append("native-image structured findings are missing")
    elif any(
        not isinstance(item, dict) or item.get("severity") not in {"blocker", "advisory"}
        for item in findings
    ):
        issues.append("native-image structured findings are invalid")
    elif any(item.get("severity") == "blocker" for item in findings):
        issues.append("native-image figure has blocking findings")
    if review.get("blind_readback_issues"):
        issues.append("native-image blind readback has blocking ambiguities")
    represented = {
        str(item.get("message") or "").strip().casefold()
        for item in findings or [] if isinstance(item, dict)
    }
    if any(
        str(item).strip().casefold() not in represented
        for item in review.get("issues") or [] if str(item).strip()
    ):
        issues.append("native-image issues lack structured severity")
    return issues


def _issues(review: dict[str, Any], best: dict[str, Any], digest: str) -> list[str]:
    _ = best, digest
    issues = [str(item) for item in review.get("issues") or [] if str(item).strip()]
    issues.extend(
        str(item.get("message") or "")
        for item in review.get("findings") or []
        if isinstance(item, dict)
        and item.get("severity") == "blocker"
        and str(item.get("message") or "").strip()
    )
    issues.extend(review_gate_issues(review))
    checklist = review.get("checklist") or {}
    failed = [key for key in RICH_SVG_HARD_CHECKS if checklist.get(key) is not True]
    if failed:
        issues.append("failed scientific or legibility checks: " + ", ".join(failed))
    improvement = str(review.get("improvement_prompt") or "").strip()
    if issues and improvement:
        issues.append("visual reviewer repair: " + improvement)
    return list(dict.fromkeys(issues))


def _normalize_accepted_advisories(review: dict[str, Any]) -> None:
    """Separate optional polish from findings after an explicit full acceptance."""
    if review_gate_issues(review):
        return
    advisories = [str(item) for item in review.get("issues") or [] if str(item).strip()]
    review["issues"] = []
    review["advisories"] = list(dict.fromkeys([
        *(review.get("advisories") or []),
        *advisories,
        *(str(item.get("message") or "") for item in review["findings"]
          if item.get("severity") == "advisory"),
    ]))


def _retryable_review_error(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}".casefold()
    return isinstance(error, (TimeoutError, ConnectionError)) or any(
        marker in text for marker in (
            "error 429", "error 500", "error 502", "error 503", "error 504",
            "timed out", "timeout", "connection reset", "temporarily unavailable",
        )
    )


async def _request_review(
    root: Path, artifact_id: str, metadata: dict[str, Any], png: Path,
    blind_readback: dict[str, Any] | None,
) -> Any:
    from .api_visual_reviewer import api_visual_reviewer

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return await api_visual_reviewer.review_rich_svg(
                project_path=root, prompt=_prompt(artifact_id, metadata, blind_readback),
                image_path=png, artifact_name=artifact_id,
                timeout_seconds=360.0,
            )
        except Exception as error:
            last_error = error
            if attempt == 2 or not _retryable_review_error(error):
                raise
            await asyncio.sleep((2.0, 5.0)[attempt])
    raise RuntimeError(f"Native-image reviewer failed without a result: {last_error}")


async def review_candidate(
    *, root: Path, artifact_id: str, metadata: dict[str, Any],
    source: Path, pdf: Path, png: Path, source_sha256: str,
) -> tuple[dict[str, Any], list[str]]:
    readback: dict[str, Any] | None = None
    readback_response: Any = None
    readback_issues: list[str] = []
    try:
        if metadata.get("blind_readback_required") is True:
            from .figure_blind_readback import (
                blind_readback_issues, request_blind_readback,
            )

            readback, readback_response = await request_blind_readback(
                root, artifact_id, png,
            )
            readback_issues = blind_readback_issues(
                readback,
                minimum_relations=_minimum_readback_relations(metadata),
            )
        response = await _request_review(
            root, artifact_id, metadata, png, readback,
        )
        review = json.loads(response.text)
    except Exception as error:
        detail = f"native-image review failed: {type(error).__name__}: {error}"
        directory, _best = _archive(
            root, artifact_id, source_sha256, (source, pdf, png),
        {"score": 0, "verdict": "error", "issues": [detail[:500]],
         "review_policy_version": REVIEW_POLICY_VERSION}, "",
        )
        return {"candidate_path": str(directory)}, [detail]
    if readback is not None:
        from .figure_blind_readback import apply_blind_readback_gate

        apply_blind_readback_gate(
            review, readback, readback_issues,
            minimum_relations=_minimum_readback_relations(metadata),
        )
    from .figure_review_findings import normalize_review_findings

    review["findings"] = normalize_review_findings(
        review, metadata, artifact_id=artifact_id,
    )
    _normalize_accepted_advisories(review)
    directory, best = _archive(
        root, artifact_id, source_sha256, (source, pdf, png),
        review, response.trace_path,
    )
    review.update({
        "protocol": PROTOCOL, "review_backend": "independent-model-api-native-vision-v1",
        "review_policy_version": REVIEW_POLICY_VERSION,
        "review_model_identity": response.model_identity,
        "review_invocation_id": response.invocation_id,
        "review_trace_path": response.trace_path,
        "candidate_path": str(directory), "source_sha256": source_sha256,
        "image_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "brief_sha256": _brief_sha256(metadata),
    })
    if readback_response is not None:
        review.update({
            "blind_readback_trace_path": readback_response.trace_path,
            "blind_readback_invocation_id": readback_response.invocation_id,
            "blind_readback_model_identity": readback_response.model_identity,
        })
    return review, _issues(review, best, source_sha256)


def commit_best_candidate(root: Path, artifact_id: str, review: dict[str, Any]) -> None:
    """Advance the best pointer only after the canonical figure commits."""
    if review.get("protocol") != PROTOCOL or review_gate_issues(review):
        raise ValueError("Only accepted native-image reviews can become best candidates")
    directory = root / ".merak" / "figure-candidates" / artifact_id
    candidate = Path(str(review["candidate_path"])).resolve()
    if candidate.parent != directory.resolve() or not (candidate / "review.json").is_file():
        raise ValueError("Visual review candidate archive is missing or outside its asset")
    previous = _load(directory / "best.json")
    if (previous.get("brief_sha256") == review.get("brief_sha256")
            and float(previous.get("score") or 0) >= float(review["score"])):
        return
    atomic_write_json(directory / "best.json", {
        "schema": 1, "protocol": PROTOCOL, "artifact_id": artifact_id,
        "score": float(review["score"]),
        "brief_sha256": str(review["brief_sha256"]),
        "candidate_sha256": str(review["source_sha256"]),
        "candidate_path": str(candidate), "verdict": "accept",
        "updated_at": time.time(),
    })


def native_review_issues(
    metadata: dict[str, Any], root: Path, source: Path, preview: Path | None,
) -> list[str]:
    """Reject legacy or stale acceptance; independently bind trace to current pixels."""
    review = metadata.get("independent_visual_review")
    review = review if isinstance(review, dict) else {}
    issues: list[str] = []
    if review.get("protocol") != PROTOCOL:
        return ["native-image figure review is missing or uses a retired protocol"]
    if review.get("review_policy_version") != REVIEW_POLICY_VERSION:
        issues.append("native-image review policy is stale")
    if review.get("brief_sha256") != _brief_sha256(metadata):
        issues.append("native-image review is stale for the scientific brief")
    issues.extend(review_gate_issues(review))
    if not source.is_file() or review.get("source_sha256") != hashlib.sha256(source.read_bytes()).hexdigest():
        issues.append("native-image review is stale for the editable SVG")
    if not preview or not preview.is_file() or review.get("image_sha256") != hashlib.sha256(preview.read_bytes()).hexdigest():
        issues.append("native-image review is stale for the rendered PNG")
    trace = Path(str(review.get("review_trace_path") or "")).resolve()
    try:
        trace.relative_to((root / ".merak" / "model-api-reviewer").resolve())
        details = _load(trace / "meta.json")
        image_hashes = details.get("image_sha256")
        image_hashes = image_hashes if isinstance(image_hashes, dict) else {}
        if not (
            details.get("success") is True
            and details.get("invocation_id") == review.get("review_invocation_id")
            and details.get("model_identity") == review.get("review_model_identity")
            and review.get("image_sha256") in image_hashes.values()
            and details.get("image_attachment_mode") == "api-native-image-content"
        ):
            issues.append("native-image review trace does not attest these pixels and model")
    except ValueError:
        issues.append("native-image review trace escapes the project")
    return issues
