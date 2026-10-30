"""Independent native-vision review over the configured model API.

This transport is a direct, stateless API request. It never starts a local
model CLI and never exposes filesystem, shell, code, or agent tools. MERAK
freezes textual evidence into the request, attaches the exact rendered pixels,
validates structured JSON locally, and persists a hash-bound trace.
"""

from __future__ import annotations

import base64
import math
import mimetypes
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from .api_visual_review_invocation import (
    API_IMAGE_ATTACHMENT_MODE as API_IMAGE_ATTACHMENT_MODE,
    API_VISUAL_REVIEW_TRANSPORT as API_VISUAL_REVIEW_TRANSPORT,
    TRACE_SCHEMA_VERSION as TRACE_SCHEMA_VERSION,
    ApiVisualReview,
    InvocationDependencies,
    invoke_visual_review,
)
from .api_visual_review_schemas import (
    FIGURE_REVIEW_SCHEMA, REVIEW_SCHEMA, RICH_SVG_REVIEW_SCHEMA,
)
from .review_evidence_packet import build_managed_evidence_packet


class ApiVisualReviewer:
    """Fresh no-tool native-image request using an isolated review session."""

    EVIDENCE_PACKET_MAX_FILES = 192
    EVIDENCE_PACKET_MAX_BYTES = 6_000_000
    EVIDENCE_PACKET_MAX_FILE_BYTES = 1_000_000
    IMAGE_LIMIT = 8
    @classmethod
    def schema_validation_errors(
        cls,
        value: Any,
        schema: dict[str, Any],
        *,
        path: str = "$",
    ) -> list[str]:
        """Validate the JSON-Schema subset used by reviewer contracts."""
        errors: list[str] = []
        expected_type = schema.get("type")
        valid = True
        if expected_type == "object":
            valid = isinstance(value, dict)
        elif expected_type == "array":
            valid = isinstance(value, list)
        elif expected_type == "string":
            valid = isinstance(value, str)
        elif expected_type == "boolean":
            valid = type(value) is bool
        elif expected_type == "integer":
            valid = type(value) is int
        elif expected_type == "number":
            valid = type(value) in {int, float} and math.isfinite(float(value))
        if not valid:
            return [f"{path} must have type {expected_type}"]
        if "const" in schema and value != schema["const"]:
            errors.append(f"{path} must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path} is outside the allowed enum")
        if expected_type == "object":
            properties = schema.get("properties")
            properties = properties if isinstance(properties, dict) else {}
            required = schema.get("required")
            required = required if isinstance(required, list) else []
            for field in required:
                if field not in value:
                    errors.append(f"{path}.{field} is required")
            if schema.get("additionalProperties") is False:
                for field in value:
                    if field not in properties:
                        errors.append(f"{path}.{field} is unsupported")
            for field, field_schema in properties.items():
                if field in value and isinstance(field_schema, dict):
                    errors.extend(cls.schema_validation_errors(
                        value[field], field_schema, path=f"{path}.{field}"
                    ))
        elif expected_type == "array":
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    errors.extend(cls.schema_validation_errors(
                        item, item_schema, path=f"{path}[{index}]"
                    ))
        elif expected_type == "string":
            minimum_length = schema.get("minLength")
            if type(minimum_length) is int and len(value) < minimum_length:
                errors.append(
                    f"{path} must contain at least {minimum_length} characters"
                )
        elif expected_type in {"number", "integer"}:
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if type(minimum) in {int, float} and value < minimum:
                errors.append(f"{path} is below minimum {minimum}")
            if type(maximum) in {int, float} and value > maximum:
                errors.append(f"{path} exceeds maximum {maximum}")
        return errors

    @classmethod
    def _managed_evidence_packet(
        cls,
        root: Path,
        evidence_paths: list[str | Path] | None,
    ) -> tuple[str, dict[str, Any]]:
        return build_managed_evidence_packet(
            root,
            evidence_paths,
            maximum_files=cls.EVIDENCE_PACKET_MAX_FILES,
            maximum_bytes=cls.EVIDENCE_PACKET_MAX_BYTES,
            maximum_file_bytes=cls.EVIDENCE_PACKET_MAX_FILE_BYTES,
        )

    @staticmethod
    def _resolve_images(
        root: Path,
        image_paths: list[str | Path] | None,
    ) -> list[Path]:
        resolved: list[Path] = []
        for raw_image in image_paths or []:
            image = Path(raw_image).expanduser()
            image = image if image.is_absolute() else root / image
            image = image.resolve()
            try:
                image.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(
                    f"Reviewer image escapes the project root: {raw_image}"
                ) from exc
            if not image.is_file() or image.stat().st_size <= 0:
                raise RuntimeError(f"Reviewer image does not exist: {image}")
            if image.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise RuntimeError(
                    f"Reviewer image format is unsupported: {image.suffix}"
                )
            if image not in resolved:
                resolved.append(image)
        if len(resolved) > ApiVisualReviewer.IMAGE_LIMIT:
            raise RuntimeError(
                f"Reviewer image packet exceeds {ApiVisualReviewer.IMAGE_LIMIT} images"
            )
        return resolved

    @staticmethod
    def _image_content(path: Path) -> dict[str, Any]:
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{encoded}",
                "detail": "high",
            },
        }

    async def invoke(
        self,
        *,
        project_path: str | Path,
        prompt: str,
        purpose: str,
        schema: dict[str, Any],
        image_paths: list[str | Path] | None = None,
        evidence_paths: list[str | Path] | None = None,
        evidence_bundle_sha256: str = "",
        timeout_seconds: float = 360.0,
        on_activity: Callable[[], Awaitable[None] | None] | None = None,
    ) -> ApiVisualReview:
        dependencies = InvocationDependencies(
            build_evidence_packet=self._managed_evidence_packet,
            resolve_images=self._resolve_images,
            encode_image=self._image_content,
            validate_schema=self.schema_validation_errors,
        )
        return await invoke_visual_review(
            project_path=project_path,
            prompt=prompt,
            purpose=purpose,
            schema=schema,
            dependencies=dependencies,
            image_paths=image_paths,
            evidence_paths=evidence_paths,
            evidence_bundle_sha256=evidence_bundle_sha256,
            timeout_seconds=timeout_seconds,
            on_activity=on_activity,
        )

    async def review_manuscript(
        self,
        *,
        project_path: str | Path,
        prompt: str,
        round_number: int,
        timeout_seconds: float,
        image_paths: list[str | Path],
        evidence_paths: list[str | Path],
        evidence_bundle_sha256: str,
        on_activity: Callable[[], Awaitable[None] | None] | None = None,
        delivery_goal: str = "submission_candidate",
    ) -> ApiVisualReview:
        from ..workflows.draft_delivery import DRAFT, draft_schema
        return await self.invoke(
            project_path=project_path,
            prompt=prompt,
            purpose=f"review-round-{int(round_number)}",
            schema=draft_schema(REVIEW_SCHEMA) if delivery_goal == DRAFT else REVIEW_SCHEMA,
            timeout_seconds=timeout_seconds,
            on_activity=on_activity,
            image_paths=image_paths,
            evidence_paths=evidence_paths,
            evidence_bundle_sha256=evidence_bundle_sha256,
        )

    async def review_figure(
        self,
        *,
        project_path: str | Path,
        prompt: str,
        image_path: str | Path,
        artifact_name: str,
        round_number: int,
        timeout_seconds: float,
    ) -> ApiVisualReview:
        safe_name = re.sub(
            r"[^a-z0-9_-]+", "-", str(artifact_name).casefold()
        ).strip("-")[:48] or "figure"
        return await self.invoke(
            project_path=project_path,
            prompt=prompt,
            purpose=f"figure-{safe_name}-round-{int(round_number)}",
            schema=FIGURE_REVIEW_SCHEMA,
            timeout_seconds=timeout_seconds,
            image_paths=[image_path],
        )

    async def review_rich_svg(
        self, *, project_path: str | Path, prompt: str,
        image_path: str | Path, artifact_name: str,
        timeout_seconds: float,
    ) -> ApiVisualReview:
        safe_name = re.sub(
            r"[^a-z0-9_-]+", "-", str(artifact_name).casefold(),
        ).strip("-")[:48] or "figure"
        return await self.invoke(
            project_path=project_path, prompt=prompt,
            purpose=f"rich-svg-{safe_name}",
            schema=RICH_SVG_REVIEW_SCHEMA,
            timeout_seconds=timeout_seconds, image_paths=[image_path],
        )


api_visual_reviewer = ApiVisualReviewer()
