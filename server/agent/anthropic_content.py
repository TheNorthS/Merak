"""Translate provider-neutral image blocks to Anthropic content blocks."""

from __future__ import annotations

import base64
import binascii
from typing import Any


def anthropic_message_content(
    content: str | list[dict[str, Any]],
) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TypeError("Message content must be text or a list of content blocks")
    converted: list[dict[str, Any]] = []
    for raw_block in content:
        if not isinstance(raw_block, dict):
            raise TypeError("Message content blocks must be JSON objects")
        block = dict(raw_block)
        if block.get("type") != "image_url":
            converted.append(block)
            continue
        image_url = block.get("image_url")
        url = str(image_url.get("url") or "") if isinstance(image_url, dict) else (
            image_url if isinstance(image_url, str) else ""
        )
        header, separator, encoded = url.partition(",")
        metadata = header[5:].split(";") if header.casefold().startswith("data:") else []
        media_type = metadata[0].casefold() if metadata else ""
        encoding_tokens = {item.casefold() for item in metadata[1:]}
        if not separator or "base64" not in encoding_tokens:
            raise ValueError("Anthropic image_url blocks must contain a base64 data URL")
        if media_type == "image/jpg":
            media_type = "image/jpeg"
        if media_type not in {"image/gif", "image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Anthropic image_url media type is unsupported: {media_type or '[empty]'}")
        compact = "".join(encoded.split())
        try:
            base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Anthropic image_url block contains invalid base64 data") from exc
        converted.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": compact},
        })
    return converted
