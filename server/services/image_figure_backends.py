"""Configured image-generation backends for qualitative scientific figures."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json
from .figure_models import FigureResult, FigureType


def _gpt_image_config(quality: str) -> tuple[str, str, str, str]:
    api_key = os.environ.get("GPT_IMAGE_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("GPT_IMAGE_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("GPT_IMAGE_MODEL", "gpt-image-2")
    normalized_quality = {"hd": "high", "standard": "medium"}.get(quality, quality)
    return api_key, base_url, model, normalized_quality


async def _persist_gpt_image(
    client: Any, item: dict[str, Any], output_dir: str,
    stem: str, model: str, description: str, size: str, quality: str,
) -> FigureResult:
    image_url, image_b64 = item.get("url"), item.get("b64_json")
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{stem}.png"
    source = directory / f"{stem}.prompt.json"
    if image_b64:
        atomic_write_bytes(output, base64.b64decode(image_b64))
    elif image_url:
        response = await client.get(image_url)
        response.raise_for_status()
        atomic_write_bytes(output, response.content)
    else:
        return FigureResult(
            False, FigureType.GPT_IMAGE,
            error="Image response contained neither url nor b64_json.",
        )
    atomic_write_json(source, {
        "model": model, "prompt": description, "size": size,
        "quality": quality, "remote_url": image_url,
        "revised_prompt": item.get("revised_prompt"),
    })
    return FigureResult(
        True, FigureType.GPT_IMAGE, output_path=str(output),
        source_path=str(source), image_url=image_url,
    )


async def generate_gpt_image(
    description: str, output_dir: str, *, size: str, quality: str,
    artifact_stem: str,
) -> FigureResult:
    api_key, base_url, model, quality = _gpt_image_config(quality)
    if not api_key:
        return FigureResult(
            False, FigureType.GPT_IMAGE,
            error="GPT_IMAGE_API_KEY / OPENAI_API_KEY not set.",
        )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.post(
                f"{base_url}/images/generations",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "prompt": f"Academic research illustration: {description}. Clean, professional, suitable for a scientific paper.",
                    "n": 1, "size": size, "quality": quality,
                },
            )
            if response.status_code != 200:
                return FigureResult(
                    False, FigureType.GPT_IMAGE,
                    error=f"API error {response.status_code}: {response.text[:200]}",
                )
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                return FigureResult(
                    False, FigureType.GPT_IMAGE,
                    error=f"Invalid JSON response: {response.text[:200]}",
                )
            if data.get("data"):
                return await _persist_gpt_image(
                    client, data["data"][0], output_dir, artifact_stem,
                    model, description, size, quality,
                )
            return FigureResult(
                False, FigureType.GPT_IMAGE,
                error=json.dumps(data.get("error", "Unknown error")),
            )
    except Exception as exc:
        return FigureResult(False, FigureType.GPT_IMAGE, error=str(exc))


async def generate_nano_banana(
    description: str, output_dir: str, *, artifact_stem: str,
    metadata: dict | None,
) -> FigureResult:
    from .gemini_figure_generator import (
        GeminiFigureProtocolError,
        GeminiPaperbananaGenerator,
        resolve_gemini_figure_config,
    )

    try:
        config = resolve_gemini_figure_config()
    except GeminiFigureProtocolError as exc:
        return FigureResult(False, FigureType.NANO_BANANA, error=str(exc))
    outcome = await GeminiPaperbananaGenerator(config).generate(
        description=description, output_dir=output_dir,
        artifact_stem=artifact_stem, metadata=metadata,
    )
    return FigureResult(
        outcome.success, FigureType.NANO_BANANA,
        output_path=outcome.output_path, source_path=outcome.source_path,
        error=outcome.error, metadata=outcome.metadata,
    )
