"""Bounded Gemini illustration generation and independent-review transaction."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from .api_visual_reviewer import API_IMAGE_ATTACHMENT_MODE, API_VISUAL_REVIEW_TRANSPORT
from .gemini_figure_protocol import (
    PROTOCOL_VERSION,
    GeminiFigureOutcome,
    GeminiFigureProtocolError,
    _atomic_json,
    _atomic_text,
    _extract_image,
    _initial_prompt,
    _layout_prompt,
    _parse_review_text,
    _response_text,
    _render_prompt,
    _review_prompt,
    _save_canonical_png,
    _sha256_bytes,
    _sha256_file,
    _sha256_tree,
    _style_prompt,
    _text_payload,
    image_review_progress_signature,
)


class GeneratorPort(Protocol):
    config: Any
    _client: Optional[httpx.AsyncClient]
    _independent_reviewer: Any

    async def _invoke(self, client: httpx.AsyncClient, **kwargs: Any) -> dict[str, Any]: ...
    def _artifact_inventory(self, run_dir: Path, project_root: Path) -> tuple[dict[str, str], dict[str, str]]: ...
    def _write_run_manifest(self, **kwargs: Any) -> Path: ...


@dataclass
class GenerationContext:
    generator: GeneratorPort
    registry: Any
    description: str
    artifact_stem: str
    project_root: Path
    run_dir: Path
    initial_prompt: str
    rounds: list[dict[str, Any]] = field(default_factory=list)
    previous_review: Optional[dict[str, Any]] = None
    accepted_image: Optional[Path] = None
    accepted_round: Optional[int] = None
    previous_progress_signature: Optional[tuple[str, str]] = None
    stop_reason: str = ""


def _prepare_context(
    generator: GeneratorPort,
    description: str,
    output_dir: str | Path,
    artifact_stem: str,
    metadata: Optional[dict[str, Any]],
) -> GenerationContext:
    from .figure_artifacts import figure_artifact_registry

    stem = re.sub(r"[^a-z0-9_-]+", "_", str(artifact_stem or "").casefold()).strip("_")[:96]
    stem = stem or "qualitative_illustration"
    requested_output = Path(output_dir).expanduser().resolve()
    figures_root = figure_artifact_registry.figures_root(requested_output)
    project_root = figure_artifact_registry.project_root(figures_root)
    token = f"{time.time_ns()}_{hashlib.sha256(description.encode('utf-8')).hexdigest()[:8]}"
    run_dir = figures_root / "ai_generated" / stem / f"run_{token}"
    run_dir.mkdir(parents=True, exist_ok=False)
    initial = _initial_prompt(description, dict(metadata or {}))
    _atomic_text(run_dir / "initial_prompt.txt", initial)
    return GenerationContext(
        generator, figure_artifact_registry, description, stem,
        project_root, run_dir, initial,
    )


def _client(context: GenerationContext) -> tuple[httpx.AsyncClient, bool]:
    existing = context.generator._client
    if existing is not None:
        return existing, False
    timeout_seconds = context.generator.config.timeout_seconds
    timeout = httpx.Timeout(
        connect=min(15.0, timeout_seconds), read=timeout_seconds,
        write=min(60.0, timeout_seconds), pool=min(15.0, timeout_seconds),
    )
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True), True


async def _layout_and_style(
    context: GenerationContext, client: httpx.AsyncClient,
    round_dir: Path,
) -> str:
    generator = context.generator
    layout_prompt = _layout_prompt(context.initial_prompt, context.previous_review)
    layout_response = await generator._invoke(
        client, round_dir=round_dir, stage="layout",
        model=generator.config.reasoning_model, prompt=layout_prompt,
        payload=_text_payload(layout_prompt),
    )
    layout = _response_text(layout_response, "layout")
    _atomic_text(round_dir / "layout_description.txt", layout)
    style_prompt = _style_prompt(layout)
    style_response = await generator._invoke(
        client, round_dir=round_dir, stage="style",
        model=generator.config.reasoning_model, prompt=style_prompt,
        payload=_text_payload(style_prompt),
    )
    style = _response_text(style_response, "style")
    _atomic_text(round_dir / "style_spec.txt", style)
    return style


async def _render_round(
    context: GenerationContext, client: httpx.AsyncClient,
    round_dir: Path, round_number: int, style: str,
) -> tuple[Path, str, int, int, str]:
    prompt = _render_prompt(style)
    payload = _text_payload(prompt)
    payload["generationConfig"] = {"responseModalities": ["TEXT", "IMAGE"]}
    response = await context.generator._invoke(
        client, round_dir=round_dir, stage="render",
        model=context.generator.config.image_model, prompt=prompt, payload=payload,
    )
    image_bytes, mime_type, render_text = _extract_image(response)
    image_path = round_dir / f"{context.artifact_stem}_round_{round_number:02d}.png"
    width, height = _save_canonical_png(image_bytes, image_path)
    if render_text:
        _atomic_text(round_dir / "render_text.txt", render_text)
    return image_path, mime_type, width, height, render_text


async def _request_review(
    context: GenerationContext, image_path: Path, style: str,
    round_dir: Path, round_number: int,
) -> tuple[Any, str]:
    relative = image_path.relative_to(context.project_root).as_posix()
    prompt = _review_prompt(context.initial_prompt, style, relative)
    _atomic_text(round_dir / "review_prompt.txt", prompt)
    _atomic_json(round_dir / "review_request.json", {
        "backend": API_VISUAL_REVIEW_TRANSPORT, "image_path": relative,
        "image_sha256": _sha256_file(image_path),
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
    })
    try:
        review = await context.generator._independent_reviewer.review(
            project_root=context.project_root, image_path=image_path, prompt=prompt,
            artifact_stem=context.artifact_stem, round_number=round_number,
            timeout_seconds=max(30.0, context.generator.config.timeout_seconds),
        )
    except Exception as exc:
        _atomic_json(round_dir / "review_response.json", {
            "protocol_error": f"Independent visual reviewer failed: {type(exc).__name__}: {str(exc)[:1000]}"
        })
        raise GeminiFigureProtocolError(
            "Independent model API visual reviewer failed; the generated image cannot be accepted."
        ) from exc
    return review, prompt


def _verified_review_trace(
    context: GenerationContext, independent: Any, image_path: Path,
) -> dict[str, str]:
    identity = str(independent.model_identity or "").strip()
    invocation_id = str(independent.invocation_id or "").strip()
    generator_models = {
        context.generator.config.reasoning_model.casefold(),
        context.generator.config.image_model.casefold(),
    }
    if not identity or identity.rsplit("/", 1)[-1].casefold() in generator_models or not invocation_id.startswith("model-api:"):
        raise GeminiFigureProtocolError(
            "Independent visual reviewer returned an invalid or non-independent model API identity."
        )
    trace = Path(independent.trace_path).expanduser().resolve()
    try:
        relative = trace.relative_to(context.project_root).as_posix()
    except ValueError as exc:
        raise GeminiFigureProtocolError("Independent visual-review trace escapes the project root.") from exc
    if not trace.is_dir():
        raise GeminiFigureProtocolError("Independent visual-review trace directory is missing.")
    try:
        meta = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeminiFigureProtocolError("Independent visual-review trace metadata is missing or invalid.") from exc
    image_hash = _sha256_file(image_path)
    valid = (
        meta.get("transport") == API_VISUAL_REVIEW_TRANSPORT
        and meta.get("image_attachment_mode") == API_IMAGE_ATTACHMENT_MODE
        and meta.get("success") is True
        and image_hash in set(map(str, dict(meta.get("image_sha256") or {}).values()))
        and str(meta.get("model_identity") or "") == identity
        and str(meta.get("invocation_id") or "") == invocation_id
    )
    if not valid:
        raise GeminiFigureProtocolError("Independent visual-review trace failed identity or image-hash verification.")
    return {
        "identity": identity, "invocation_id": invocation_id,
        "trace_relative": relative, "trace_sha256": _sha256_tree(trace),
        "image_sha256": image_hash,
    }


def _review_result(
    context: GenerationContext, independent: Any, trace: dict[str, str],
    image_path: Path, review_prompt: str, round_dir: Path,
    round_number: int, mime_type: str, width: int, height: int,
) -> dict[str, Any]:
    review = _parse_review_text(independent.text, {
        "invocation_id": trace["invocation_id"], "model_identity": trace["identity"],
        "trace_path": trace["trace_relative"],
    })
    _atomic_json(round_dir / "review_response.json", {
        "review": json.loads(independent.text),
        "invocation_id": trace["invocation_id"], "model_identity": trace["identity"],
        "trace_path": trace["trace_relative"], "trace_sha256": trace["trace_sha256"],
    })
    local_issues = context.registry.raster_visual_quality_issues(image_path)
    if local_issues:
        review["local_quality_issues"] = local_issues
        review["issues"] = list(dict.fromkeys([
            *review["issues"], *[f"Local raster gate: {item}" for item in local_issues],
        ]))
        review["score"] = min(float(review["score"]), 7.0)
        review["critical_checks_pass"] = False
    passed = (
        float(review["score"]) >= context.generator.config.target_score
        and review["critical_checks_pass"] is True and review["model_verdict"] == "accept"
    )
    review.update({
        "round": round_number, "status": "passed" if passed else "failed",
        "mime_type": mime_type, "width": width, "height": height,
        "render_sha256": trace["image_sha256"], "review_image_sha256": trace["image_sha256"],
        "review_backend": API_VISUAL_REVIEW_TRANSPORT,
        "review_invocation_id": trace["invocation_id"],
        "review_model_identity": trace["identity"],
        "review_trace_path": trace["trace_relative"], "review_trace_sha256": trace["trace_sha256"],
        "review_prompt_sha256": _sha256_bytes(review_prompt.encode("utf-8")),
        "review_coordinator_verified": True,
        "review_response_sha256": _sha256_file(round_dir / "review_response.json"),
        "reviewed_at": time.time(),
    })
    return review


def _record_progress(
    context: GenerationContext, review: dict[str, Any], image_path: Path,
    round_dir: Path, round_number: int,
) -> bool:
    passed = review["status"] == "passed"
    signature = image_review_progress_signature(str(review["render_sha256"]), review)
    no_progress = bool(not passed and context.previous_progress_signature == signature)
    if no_progress:
        context.stop_reason = "no_progress_same_image_and_review_findings"
        review.update({
            "stop_reason": context.stop_reason, "terminal": True,
            "stopped_for_no_progress": True,
        })
    context.previous_progress_signature = signature
    _atomic_json(round_dir / "review.json", review)
    context.rounds.append(review)
    if passed:
        context.accepted_image, context.accepted_round = image_path, round_number
    elif not no_progress:
        context.previous_review = review
    return passed or no_progress


async def _execute_round(
    context: GenerationContext, client: httpx.AsyncClient, round_number: int,
) -> bool:
    round_dir = context.run_dir / f"round_{round_number:02d}"
    round_dir.mkdir(parents=True, exist_ok=False)
    style = await _layout_and_style(context, client, round_dir)
    image_path, mime_type, width, height, _render_text = await _render_round(
        context, client, round_dir, round_number, style,
    )
    independent, prompt = await _request_review(
        context, image_path, style, round_dir, round_number,
    )
    trace = _verified_review_trace(context, independent, image_path)
    review = _review_result(
        context, independent, trace, image_path, prompt, round_dir,
        round_number, mime_type, width, height,
    )
    return _record_progress(context, review, image_path, round_dir, round_number)


def _manifest(context: GenerationContext, status: str, error: str = "") -> Path:
    return context.generator._write_run_manifest(
        run_dir=context.run_dir, project_root=context.project_root,
        artifact_stem=context.artifact_stem, description=context.description,
        initial_prompt=context.initial_prompt, status=status, rounds=context.rounds,
        accepted_round=context.accepted_round if status == "accepted" else None,
        error=error,
    )


def _failed_outcome(
    context: GenerationContext, error: str, *, failure_payload: Optional[dict[str, Any]] = None,
) -> GeminiFigureOutcome:
    payload = dict(failure_payload or {})
    payload.setdefault("error", error)
    payload.setdefault("rounds_completed", len(context.rounds))
    _atomic_json(context.run_dir / "failure.json", payload)
    source = _manifest(context, "failed", error)
    paths, hashes = context.generator._artifact_inventory(context.run_dir, context.project_root)
    return GeminiFigureOutcome(False, None, str(source), error, {
        "protocol": PROTOCOL_VERSION, "visual_review_rounds": context.rounds,
        "stop_reason": context.stop_reason, "terminal": True,
        "protocol_artifacts": paths, "protocol_artifact_sha256": hashes,
    })


def _accepted_outcome(context: GenerationContext) -> GeminiFigureOutcome:
    assert context.accepted_image is not None and context.accepted_round is not None
    final_path = context.run_dir / f"{context.artifact_stem}.png"
    shutil.copyfile(context.accepted_image, final_path)
    relative = final_path.relative_to(context.project_root).as_posix()
    label = re.sub(r"[^a-z0-9]+", "-", context.artifact_stem.casefold()).strip("-")
    _atomic_text(context.run_dir / "latex_include.tex", (
        "% === AI-Generated Figure ===\n\\begin{figure*}[t]\n    \\centering\n"
        f"    \\includegraphics[width=0.95\\textwidth]{{../{relative}}}\n"
        f"    \\caption{{{context.description.strip()}}}\n"
        f"    \\label{{fig:{label or 'ai-illustration'}}}\n\\end{{figure*}}\n"
    ))
    _atomic_json(context.run_dir / "review_log.json", context.rounds)
    source = _manifest(context, "accepted")
    paths, hashes = context.generator._artifact_inventory(context.run_dir, context.project_root)
    variants = {"png": str(final_path), **{
        f"round_{item['round']:02d}_png": str(
            context.run_dir / f"round_{int(item['round']):02d}"
            / f"{context.artifact_stem}_round_{int(item['round']):02d}.png"
        ) for item in context.rounds
    }}
    last = context.rounds[-1]
    return GeminiFigureOutcome(True, str(final_path), str(source), None, {
        "protocol": PROTOCOL_VERSION, "generator": "gemini-paperbanana",
        "renderer": context.generator.config.image_model,
        "reasoning_model": context.generator.config.reasoning_model,
        "image_model": context.generator.config.image_model,
        "review_backend": API_VISUAL_REVIEW_TRANSPORT,
        "review_model": last["review_model_identity"],
        "generator_skill": "paper-illustration", "skill": "paper-illustration",
        "target_score": context.generator.config.target_score,
        "max_iterations": context.generator.config.max_iterations,
        "accepted_round": context.accepted_round, "accepted_score": last["score"],
        "visual_review_rounds": context.rounds, "protocol_artifacts": paths,
        "protocol_artifact_sha256": hashes, "output_sha256": _sha256_file(final_path),
        "source_prompt_sha256": _sha256_file(source),
        "final_output_sha256": _sha256_file(final_path),
        "final_source_sha256": _sha256_file(source), "_rendered_variant_paths": variants,
    })


async def generate_illustration(
    generator: GeneratorPort, *, description: str, output_dir: str | Path,
    artifact_stem: str, metadata: Optional[dict[str, Any]] = None,
) -> GeminiFigureOutcome:
    context = _prepare_context(generator, description, output_dir, artifact_stem, metadata)
    client, owns_client = _client(context)
    try:
        if not generator._independent_reviewer.available():
            raise GeminiFigureProtocolError(
                "Independent model API visual reviewer is unavailable; Gemini/Paperbanana cannot self-approve."
            )
        for round_number in range(1, generator.config.max_iterations + 1):
            if await _execute_round(context, client, round_number):
                break
        if context.accepted_image is not None:
            return _accepted_outcome(context)
        best = max(context.rounds, key=lambda item: float(item.get("score") or 0), default={})
        error = (
            "Independent visual-review stopped for no progress: two consecutive rounds produced "
            "the same image SHA256 and normalized review findings."
            if context.stop_reason else
            f"Independent visual-review budget exhausted without a score >= {generator.config.target_score} and all critical checks passing."
        )
        return _failed_outcome(context, error, failure_payload={
            "error": error, "best_round": best.get("round"), "best_score": best.get("score"),
            "rounds_attempted": len(context.rounds), "stop_reason": context.stop_reason,
            "terminal": True,
        })
    except GeminiFigureProtocolError as exc:
        return _failed_outcome(context, str(exc), failure_payload={
            "error": str(exc), "status_code": exc.status_code,
            "response": exc.audit_payload, "rounds_completed": len(context.rounds),
        })
    except Exception as exc:
        error = f"Gemini figure protocol failed locally ({type(exc).__name__}: {str(exc)[:500]})."
        try:
            return _failed_outcome(context, error)
        except Exception:
            return GeminiFigureOutcome(False, None, None, error, {
                "protocol": PROTOCOL_VERSION, "visual_review_rounds": context.rounds,
            })
    finally:
        if owns_client:
            await client.aclose()
