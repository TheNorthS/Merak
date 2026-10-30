"""Strict Gemini/Paperbanana academic-illustration protocol.

This module implements the native counterpart of the bundled
``/paper-illustration`` skill.  It deliberately owns only the generative
illustration backend; deterministic FigureSpec and quantitative plotting stay
in their existing code paths.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from PIL import Image, UnidentifiedImageError

from ..utils.atomic_write import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_REASONING_MODEL = "gemini-3-pro-preview"
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_MAX_ITERATIONS = 5
TARGET_SCORE = 9
PROTOCOL_VERSION = "merak-paperbanana-v1"
MAX_IMAGE_BYTES = 40 * 1024 * 1024

REVIEW_CHECKS = (
    "arrow_correctness",
    "block_content",
    "arrow_visibility",
    "arrow_labels",
    "visual_appeal",
    "layout_flow",
    "style_compliance",
    "text_readability",
    "no_visual_artifacts",
)


class GeminiFigureProtocolError(RuntimeError):
    """A strict, user-facing protocol failure with optional audit material."""

    def __init__(
        self,
        message: str,
        *,
        audit_payload: Any = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.audit_payload = audit_payload
        self.status_code = status_code


@dataclass(frozen=True)
class GeminiFigureConfig:
    api_key: str
    base_url: str = DEFAULT_GEMINI_BASE_URL
    reasoning_model: str = DEFAULT_REASONING_MODEL
    image_model: str = DEFAULT_IMAGE_MODEL
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    target_score: int = TARGET_SCORE
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("Gemini API key is empty.")
        if not self.base_url.strip():
            raise ValueError("Gemini base URL is empty.")
        if not all(model.strip() for model in (self.reasoning_model, self.image_model)):
            raise ValueError("Gemini figure model names must not be empty.")
        if not 1 <= int(self.max_iterations) <= DEFAULT_MAX_ITERATIONS:
            raise ValueError(
                f"Gemini figure max_iterations must be between 1 and "
                f"{DEFAULT_MAX_ITERATIONS}."
            )
        if not TARGET_SCORE <= int(self.target_score) <= 10:
            raise ValueError("Gemini figure target_score must be between 9 and 10.")
        if not 5.0 <= float(self.timeout_seconds) <= 300.0:
            raise ValueError("Gemini figure timeout must be between 5 and 300 seconds.")


@dataclass
class GeminiFigureOutcome:
    success: bool
    output_path: Optional[str]
    source_path: Optional[str]
    error: Optional[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IndependentVisualReview:
    text: str
    invocation_id: str
    model_identity: str
    trace_path: str


class ApiIndependentVisualReviewer:
    """Fresh independent model-API request with the round PNG attached."""

    @staticmethod
    def available() -> bool:
        from ..agent import ModelRole, model_router

        try:
            _reviewer_name, _reviewer, reviewer_identity = (
                model_router.get_isolated_provider_route(
                    ModelRole.REVIEWER,
                )
            )
        except RuntimeError:
            return False
        return bool(reviewer_identity)

    @staticmethod
    async def review(
        *,
        project_root: Path,
        image_path: Path,
        prompt: str,
        artifact_stem: str,
        round_number: int,
        timeout_seconds: float,
    ) -> IndependentVisualReview:
        from .api_visual_reviewer import api_visual_reviewer

        result = await api_visual_reviewer.review_figure(
            project_path=project_root,
            prompt=prompt,
            image_path=image_path,
            artifact_name=artifact_stem,
            round_number=round_number,
            timeout_seconds=timeout_seconds,
        )
        return IndependentVisualReview(
            text=result.text,
            invocation_id=result.invocation_id,
            model_identity=result.model_identity,
            trace_path=result.trace_path,
        )


def _bounded_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _bounded_float(
    raw: Any,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _configured_gemini_values() -> tuple[str, str]:
    """Read the saved Settings values without making them mandatory.

    Saved IDE settings are authoritative for desktop workflow runs.
    Environment values are used only for direct/headless execution when no
    saved API key exists.
    """

    try:
        from ..api.settings import load_settings

        models = load_settings().models
        return (
            str(getattr(models, "gemini_api_key", "") or "").strip(),
            str(getattr(models, "gemini_base_url", "") or "").strip(),
        )
    except Exception:
        return "", ""


def _normalize_native_base_url(raw: str) -> str:
    """Normalize a Gemini host/version prefix for native generateContent calls."""

    value = str(raw or "").strip() or DEFAULT_GEMINI_BASE_URL
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Gemini base URL must be an absolute HTTP(S) URL.")
    path = parsed.path.rstrip("/")
    if path.endswith("/openai"):
        path = path[: -len("/openai")]
    if not path:
        path = "/v1beta"
    if path.endswith("/models"):
        path = path[: -len("/models")]
    if "/models/" in path or path.endswith(":generateContent"):
        raise ValueError(
            "Gemini base URL must be a host or API-version prefix, not a model endpoint."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _public_base_url(raw: str) -> str:
    """Return a provenance-safe URL without credentials, query, or fragment."""

    parsed = urlsplit(raw)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", "")).rstrip("/")


def resolve_gemini_figure_config() -> GeminiFigureConfig:
    configured_key, configured_base = _configured_gemini_values()
    # A verified IDE configuration must be the exact credential/base pair used
    # by workflow runs. Environment values are a fallback for direct/headless
    # use only when no saved key exists.
    if configured_key:
        api_key = configured_key
        raw_base = configured_base or DEFAULT_GEMINI_BASE_URL
    else:
        api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
        raw_base = str(
            os.environ.get("GEMINI_BASE_URL") or DEFAULT_GEMINI_BASE_URL
        )
    if not api_key:
        raise GeminiFigureProtocolError(
            "Gemini illustration requires a configured Gemini API key "
            "(Settings or GEMINI_API_KEY)."
        )
    try:
        base_url = _normalize_native_base_url(raw_base)
    except ValueError as exc:
        raise GeminiFigureProtocolError(str(exc)) from exc
    reasoning_model = str(
        os.environ.get("GEMINI_FIGURE_REASONING_MODEL")
        or DEFAULT_REASONING_MODEL
    ).strip() or DEFAULT_REASONING_MODEL
    image_model = str(
        os.environ.get("GEMINI_FIGURE_IMAGE_MODEL")
        or DEFAULT_IMAGE_MODEL
    ).strip() or DEFAULT_IMAGE_MODEL
    max_iterations = _bounded_int(
        os.environ.get("GEMINI_FIGURE_MAX_ITERATIONS"),
        DEFAULT_MAX_ITERATIONS,
        1,
        DEFAULT_MAX_ITERATIONS,
    )
    timeout_seconds = _bounded_float(
        os.environ.get("GEMINI_FIGURE_TIMEOUT_SECONDS"),
        180.0,
        5.0,
        300.0,
    )
    return GeminiFigureConfig(
        api_key=api_key,
        base_url=base_url,
        reasoning_model=reasoning_model,
        image_model=image_model,
        max_iterations=max_iterations,
        target_score=TARGET_SCORE,
        timeout_seconds=timeout_seconds,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _atomic_text(path: Path, text: str) -> None:
    atomic_write_text(path, str(text))


def _request_audit_payload(payload: dict[str, Any], image_path: str = "") -> dict[str, Any]:
    """Keep prompts auditable without duplicating review-image base64 in requests."""

    cloned = json.loads(json.dumps(payload))
    for content in cloned.get("contents") or []:
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict) or not isinstance(inline.get("data"), str):
                continue
            encoded = re.sub(r"\s+", "", inline["data"])
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raw = b""
            inline["data"] = {
                "omitted_from_request_audit": True,
                "image_path": image_path,
                "encoded_sha256": _sha256_bytes(encoded.encode("ascii", errors="ignore")),
                "decoded_sha256": _sha256_bytes(raw) if raw else "",
                "decoded_bytes": len(raw),
            }
    return cloned


def _response_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise GeminiFigureProtocolError("Gemini returned a non-object JSON response.")
    if payload.get("error"):
        raise GeminiFigureProtocolError(
            "Gemini returned an API error envelope.",
            audit_payload=payload,
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = payload.get("promptFeedback") or payload.get("prompt_feedback") or {}
        raise GeminiFigureProtocolError(
            "Gemini response contains no candidates.",
            audit_payload={"response": payload, "prompt_feedback": feedback},
        )
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise GeminiFigureProtocolError(
            "Gemini response candidate is malformed.",
            audit_payload=payload,
        )
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise GeminiFigureProtocolError(
            "Gemini response candidate contains no content parts.",
            audit_payload=payload,
        )
    return [part for part in parts if isinstance(part, dict)]


def _response_text(payload: dict[str, Any], stage: str) -> str:
    text = "\n".join(
        str(part.get("text") or "").strip()
        for part in _response_parts(payload)
        if str(part.get("text") or "").strip()
    ).strip()
    if not text:
        raise GeminiFigureProtocolError(
            f"Gemini {stage} response contains no text.",
            audit_payload=payload,
        )
    return text


def _extract_image(payload: dict[str, Any]) -> tuple[bytes, str, str]:
    images: list[tuple[str, str]] = []
    response_text: list[str] = []
    for part in _response_parts(payload):
        text = str(part.get("text") or "").strip()
        if text:
            response_text.append(text)
        inline = part.get("inlineData") or part.get("inline_data")
        if not isinstance(inline, dict):
            continue
        mime_type = str(
            inline.get("mimeType") or inline.get("mime_type") or ""
        ).strip().casefold()
        encoded = inline.get("data")
        if mime_type.startswith("image/") and isinstance(encoded, str):
            images.append((mime_type, encoded))
    if len(images) != 1:
        raise GeminiFigureProtocolError(
            "Gemini image response must contain exactly one inline image "
            f"(found {len(images)}).",
            audit_payload=payload,
        )
    mime_type, encoded = images[0]
    compact = re.sub(r"\s+", "", encoded)
    try:
        image_bytes = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GeminiFigureProtocolError(
            "Gemini image response contains invalid base64.",
            audit_payload=payload,
        ) from exc
    if not image_bytes:
        raise GeminiFigureProtocolError(
            "Gemini image response decoded to an empty image.",
            audit_payload=payload,
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise GeminiFigureProtocolError(
            f"Gemini image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit.",
            audit_payload={"mime_type": mime_type, "bytes": len(image_bytes)},
        )
    return image_bytes, mime_type, "\n".join(response_text).strip()


def _save_canonical_png(image_bytes: bytes, path: Path) -> tuple[int, int]:
    """Decode untrusted model bytes and persist a real, canonical PNG."""

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(image_bytes)) as opened:
            width, height = opened.size
            if width < 64 or height < 64 or width > 8192 or height > 8192:
                raise GeminiFigureProtocolError(
                    f"Gemini image dimensions are invalid ({width}x{height})."
                )
            rgba = opened.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, "#ffffff")
            canvas.paste(rgba, mask=rgba.getchannel("A"))
    except GeminiFigureProtocolError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise GeminiFigureProtocolError(
            "Gemini returned bytes that are not a decodable image."
        ) from exc
    encoded = io.BytesIO()
    canvas.save(encoded, format="PNG", optimize=True)
    atomic_write_bytes(path, encoded.getvalue())
    return width, height


def _parse_review_text(raw: str, audit_payload: Any) -> dict[str, Any]:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        review = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise GeminiFigureProtocolError(
            "Independent visual review is not valid JSON.",
            audit_payload=audit_payload,
        ) from exc
    if not isinstance(review, dict):
        raise GeminiFigureProtocolError(
            "Independent visual review must be a JSON object.",
            audit_payload=audit_payload,
        )
    score = review.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise GeminiFigureProtocolError(
            "Independent visual review has no numeric score.",
            audit_payload=audit_payload,
        )
    score_value = float(score)
    if score_value < 1 or score_value > 10:
        raise GeminiFigureProtocolError(
            "Independent visual review score must be between 1 and 10.",
            audit_payload=audit_payload,
        )
    checklist = review.get("checklist")
    if not isinstance(checklist, dict):
        raise GeminiFigureProtocolError(
            "Independent visual review has no checklist object.",
            audit_payload=audit_payload,
        )
    missing_checks = [name for name in REVIEW_CHECKS if not isinstance(checklist.get(name), bool)]
    if missing_checks:
        raise GeminiFigureProtocolError(
            "Independent visual review is missing boolean checks: "
            + ", ".join(missing_checks),
            audit_payload=audit_payload,
        )
    issues = review.get("issues")
    if not isinstance(issues, list) or any(not isinstance(item, str) for item in issues):
        raise GeminiFigureProtocolError(
            "Independent visual review issues must be a string array.",
            audit_payload=audit_payload,
        )
    strengths = review.get("strengths")
    if not isinstance(strengths, list) or any(
        not isinstance(item, str) for item in strengths
    ):
        raise GeminiFigureProtocolError(
            "Independent visual review strengths must be a string array.",
            audit_payload=audit_payload,
        )
    improvement_prompt = review.get("improvement_prompt")
    if not isinstance(improvement_prompt, str):
        raise GeminiFigureProtocolError(
            "Independent visual review improvement_prompt must be a string.",
            audit_payload=audit_payload,
        )
    critical_pass = all(checklist[name] is True for name in REVIEW_CHECKS)
    return {
        "reported_score": score_value,
        "score": score_value,
        "issues": [" ".join(item.split()) for item in issues if item.strip()],
        "strengths": [" ".join(item.split()) for item in strengths if item.strip()],
        "improvement_prompt": improvement_prompt.strip(),
        "checklist": {name: checklist[name] for name in REVIEW_CHECKS},
        "critical_checks_pass": critical_pass,
        "model_verdict": str(review.get("verdict") or "").strip().casefold(),
    }


def normalized_review_findings(review: dict[str, Any]) -> dict[str, Any]:
    """Canonical semantic findings, excluding score/trace/timestamp churn."""

    def normalize(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()

    checklist = review.get("checklist") if isinstance(review.get("checklist"), dict) else {}
    issues = {
        normalize(item)
        for item in [
            *list(review.get("issues") or []),
            *list(review.get("local_quality_issues") or []),
        ]
        if normalize(item)
    }
    return {
        "issues": sorted(issues),
        "failed_checks": sorted(
            normalize(name)
            for name in REVIEW_CHECKS
            if checklist.get(name) is not True
        ),
        "improvement_prompt": normalize(review.get("improvement_prompt")),
        "verdict": normalize(review.get("model_verdict") or review.get("verdict")),
    }


def image_review_progress_signature(
    image_sha256: str,
    review: dict[str, Any],
) -> tuple[str, str]:
    findings = json.dumps(
        normalized_review_findings(review),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        str(image_sha256 or "").strip().casefold(),
        hashlib.sha256(findings.encode("utf-8")).hexdigest(),
    )


def _initial_prompt(description: str, metadata: dict[str, Any]) -> str:
    from .publication_figure_labels import publication_label_texts

    publication_terms = publication_label_texts(metadata.get("publication_labels"))
    components = "\n".join(f"- {term}" for term in publication_terms) or (
        "- Derive exact component labels only from the requested figure description."
    )
    return f"""Create a PROFESSIONAL, VISUALLY APPEALING publication-quality academic
diagram following CVPR/ICLR/NeurIPS standards.

SCIENTIFIC REQUEST
- Description: {description.strip()}
- Scientific role: {str(metadata.get("scientific_role") or "qualitative")}
- Scientific question: {str(metadata.get("scientific_question") or description).strip()}
- Intended comparison: {str(metadata.get("intended_comparison") or "not specified").strip()}
- Requested visual encoding: {str(metadata.get("visual_encoding") or "academic conceptual diagram").strip()}

REQUIRED DOMAIN-FACING TERMS
{components}

CONTENT INTEGRITY
- Do not invent measurements, numerical results, citations, logos, datasets, or
  method components absent from the request.
- Preserve every exact domain-facing label supplied above.
- Make component relationships and arrow direction explicit.

LAYOUT AND STYLE
- Prefer a clean left-to-right flow on a white background.
- Group related modules with balanced whitespace and consistent sizing.
- Use 3-4 coordinated, print-friendly colors with subtle same-color gradients.
- Use sans-serif text, minimum 14 pt at final output scale.
- Use rounded corners and visible internal structure without decorative clutter.
- Every connection must have a thick dark stroke, a clear arrowhead, an accurate
  direction, and a readable data-flow label.
- Avoid arrow crossings, rainbow palettes, heavy shadows, glow, 3D perspective,
  clip art, watermarks, and tiny text.

Return a detailed rendering specification, not an image."""


def _layout_prompt(initial: str, previous_review: Optional[dict[str, Any]]) -> str:
    refinement = ""
    if previous_review:
        issues = "\n".join(
            f"- {item}" for item in previous_review.get("issues") or []
        ) or "- The prior candidate did not meet the strict acceptance contract."
        improvement = str(previous_review.get("improvement_prompt") or "").strip()
        strengths = "\n".join(
            f"- {item}" for item in previous_review.get("strengths") or []
        ) or "- Preserve all scientifically correct content."
        refinement = f"""

PREVIOUS ROUND — EXACT CORRECTIONS REQUIRED
Issues:
{issues}
Reviewer improvement instruction:
{improvement or "Correct every failed checklist item explicitly."}
Elements to preserve:
{strengths}
"""
    return f"""You are an expert academic-figure layout designer.

Optimize the following figure request into a precise layout specification:

{initial}
{refinement}

Return:
1. exact component positions and relative sizes;
2. spacing and grouping;
3. explicit source -> target arrow routing with labels and no crossings;
4. visual hierarchy and internal substructure;
5. a complete label inventory.

Do not omit, rename, or invent scientific content."""


def _style_prompt(layout: str) -> str:
    return f"""You are a strict CVPR/ICLR/NeurIPS figure style verifier.

Review and ENHANCE this optimized layout specification:

{layout}

Return one complete, render-ready specification. Enforce:
- white background and a coordinated 3-4 color, grayscale-readable palette;
- sans-serif text at least 14 pt and exact, correctly spelled labels;
- thick 5-6 px dark arrows, large arrowheads, correct direction, and a readable
  label on every connection;
- rounded corners, subtle same-color gradients, clear hierarchy, and visible
  internal structure;
- no crossings, cropping, tiny text, heavy shadows, glow, rainbow gradients,
  decorative icons, photorealism, watermark, title, caption, or figure number.

Do not add scientific content that is absent from the layout."""


def _render_prompt(style_spec: str) -> str:
    return f"""Render exactly one publication-quality academic diagram from this
verified specification:

{style_spec}

The output must be a clean, sharp, high-resolution figure on a white background.
It must contain no prose outside the diagram, no caption, no figure number, and
no watermark. Preserve exact labels and arrow directions. Return one image."""


def _review_prompt(initial: str, style_spec: str, image_relative: str) -> str:
    checks = json.dumps(
        {name: True for name in REVIEW_CHECKS},
        ensure_ascii=False,
        indent=4,
    )
    return f"""Act as a STRICT independent visual reviewer. MERAK attached this
exact image as native model-API image content: {image_relative}

Inspect the attached pixels directly; do not infer appearance from filenames or
prompts. Compare the pixels against both the original request and the render
specification. Inspect every block, every label, and every arrow individually.

ORIGINAL REQUEST
{initial}

RENDER SPECIFICATION
{style_spec}

SCORING RULES
- Any wrong arrow direction caps score at 6.
- Any wrong or missing block content caps score at 7.
- Any missing/thin/unlabeled arrow caps score at 7.
- Cropping, unreadable text, crossings, or excessive decoration cap score at 7.
- A plain, visually under-designed figure caps score at 8.
- Score 9-10 only when every checklist item passes and the figure is ready for
  direct paper use.

Return JSON only with exactly these fields:
{{
  "score": 1-10,
  "verdict": "accept" or "refine",
  "issues": ["specific pixel-grounded issue -> exact correction"],
  "strengths": ["specific element worth preserving"],
  "improvement_prompt": "targeted instructions for the next rendering round",
  "checklist": {checks}
}}

Never claim a check passed unless it is visibly verifiable in the attached image."""


def _text_payload(prompt: str, *, json_response: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if json_response:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "required": [
                    "score",
                    "verdict",
                    "issues",
                    "strengths",
                    "improvement_prompt",
                    "checklist",
                ],
                "properties": {
                    "score": {"type": "NUMBER"},
                    "verdict": {"type": "STRING", "enum": ["accept", "refine"]},
                    "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "improvement_prompt": {"type": "STRING"},
                    "checklist": {
                        "type": "OBJECT",
                        "required": list(REVIEW_CHECKS),
                        "properties": {
                            name: {"type": "BOOLEAN"} for name in REVIEW_CHECKS
                        },
                    },
                },
            },
        }
    return payload
