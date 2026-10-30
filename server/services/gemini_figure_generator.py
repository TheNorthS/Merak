"""Gemini/Paperbanana stateful generation transaction.

Protocol parsing, configuration primitives, prompts, and response validation
live in gemini_figure_protocol. Public names remain import-compatible here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

from .gemini_figure_protocol import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_REASONING_MODEL,
    PROTOCOL_VERSION,
    REVIEW_CHECKS as REVIEW_CHECKS,
    TARGET_SCORE,
    ApiIndependentVisualReviewer,
    GeminiFigureConfig,
    GeminiFigureOutcome,
    GeminiFigureProtocolError,
    IndependentVisualReview as IndependentVisualReview,
    _atomic_json,
    _atomic_text,
    _bounded_float,
    _bounded_int,
    _normalize_native_base_url,
    _public_base_url,
    _request_audit_payload,
    _save_canonical_png as _save_canonical_png,
    _sha256_file,
    image_review_progress_signature as image_review_progress_signature,
    normalized_review_findings as normalized_review_findings,
)
from .api_visual_reviewer import API_VISUAL_REVIEW_TRANSPORT
from .gemini_generation_transaction import generate_illustration

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

class GeminiPaperbananaGenerator:
    """Run layout -> style -> image -> strict visual review for at most 5 rounds."""

    def __init__(
        self,
        config: GeminiFigureConfig,
        *,
        client: Optional[httpx.AsyncClient] = None,
        independent_reviewer: Any = None,
    ) -> None:
        self.config = config
        self._client = client
        self._independent_reviewer = (
            independent_reviewer or ApiIndependentVisualReviewer()
        )

    def _endpoint(self, model: str) -> str:
        safe_model = quote(model.strip(), safe="-_.")
        return f"{self.config.base_url.rstrip('/')}/models/{safe_model}:generateContent"

    async def _post(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await client.post(
                self._endpoint(model),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.config.api_key,
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise GeminiFigureProtocolError(
                "Gemini figure request timed out within the configured bound."
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiFigureProtocolError(
                f"Gemini figure request failed ({type(exc).__name__})."
            ) from exc
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise GeminiFigureProtocolError(
                f"Gemini returned non-JSON HTTP {response.status_code}.",
                audit_payload={
                    "status_code": response.status_code,
                    "body_excerpt": response.text[:2000],
                },
                status_code=response.status_code,
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise GeminiFigureProtocolError(
                f"Gemini API returned HTTP {response.status_code}.",
                audit_payload=body,
                status_code=response.status_code,
            )
        if not isinstance(body, dict):
            raise GeminiFigureProtocolError(
                "Gemini returned a non-object JSON response.",
                audit_payload=body,
                status_code=response.status_code,
            )
        if body.get("error"):
            raise GeminiFigureProtocolError(
                "Gemini returned an API error envelope.",
                audit_payload=body,
                status_code=response.status_code,
            )
        return body

    async def _invoke(
        self,
        client: httpx.AsyncClient,
        *,
        round_dir: Path,
        stage: str,
        model: str,
        prompt: str,
        payload: dict[str, Any],
        review_image_path: str = "",
    ) -> dict[str, Any]:
        _atomic_text(round_dir / f"{stage}_prompt.txt", prompt)
        _atomic_json(
            round_dir / f"{stage}_request.json",
            _request_audit_payload(payload, review_image_path),
        )
        try:
            response = await self._post(client, model=model, payload=payload)
        except GeminiFigureProtocolError as exc:
            _atomic_json(
                round_dir / f"{stage}_response.json",
                {
                    "protocol_error": str(exc),
                    "status_code": exc.status_code,
                    "response": exc.audit_payload,
                },
            )
            raise
        _atomic_json(round_dir / f"{stage}_response.json", response)
        return response

    @staticmethod
    def _artifact_inventory(run_dir: Path, project_root: Path) -> tuple[dict[str, str], dict[str, str]]:
        paths: dict[str, str] = {}
        hashes: dict[str, str] = {}
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.suffix == ".tmp":
                continue
            try:
                relative = path.relative_to(project_root).as_posix()
            except ValueError:
                relative = path.as_posix()
            key = path.relative_to(run_dir).as_posix()
            paths[key] = relative
            hashes[key] = _sha256_file(path)
        return paths, hashes

    def _write_run_manifest(
        self,
        *,
        run_dir: Path,
        project_root: Path,
        artifact_stem: str,
        description: str,
        initial_prompt: str,
        status: str,
        rounds: list[dict[str, Any]],
        accepted_round: Optional[int],
        error: str = "",
    ) -> Path:
        artifact_paths, artifact_hashes = self._artifact_inventory(
            run_dir, project_root
        )
        manifest_path = run_dir / f"{artifact_stem}.prompt.json"
        payload = {
            "schema": 1,
            "protocol": PROTOCOL_VERSION,
            "status": status,
            "terminal": status in {"accepted", "failed"},
            "stop_reason": str(rounds[-1].get("stop_reason") or "") if rounds else "",
            "description": description,
            "initial_prompt": initial_prompt,
            "reasoning_model": self.config.reasoning_model,
            "image_model": self.config.image_model,
            "review_backend": API_VISUAL_REVIEW_TRANSPORT,
            "review_model_identities": sorted({
                str(item.get("review_model_identity") or "")
                for item in rounds
                if str(item.get("review_model_identity") or "")
            }),
            "base_url": _public_base_url(self.config.base_url),
            "target_score": self.config.target_score,
            "max_iterations": self.config.max_iterations,
            "accepted_round": accepted_round,
            "accepted_score": next((
                item.get("score")
                for item in rounds
                if item.get("round") == accepted_round
            ), None),
            "rounds": rounds,
            "error": error,
            "artifacts": artifact_paths,
            "artifact_sha256": artifact_hashes,
        }
        _atomic_json(manifest_path, payload)
        return manifest_path

    async def generate(
        self,
        *,
        description: str,
        output_dir: str | Path,
        artifact_stem: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> GeminiFigureOutcome:
        return await generate_illustration(
            self,
            description=description,
            output_dir=output_dir,
            artifact_stem=artifact_stem,
            metadata=metadata,
        )
