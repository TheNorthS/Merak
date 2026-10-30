from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from server.api.files import (
    CreateRequest,
    create_file_or_dir,
    get_pptx_slides,
    read_binary,
)


def test_create_file_is_exclusive_and_never_overwrites_existing_content(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"

    created = asyncio.run(create_file_or_dir(CreateRequest(path=str(target))))
    target.write_text("researcher content", encoding="utf-8")
    with pytest.raises(HTTPException) as duplicate:
        asyncio.run(create_file_or_dir(CreateRequest(path=str(target))))

    assert created["status"] == "created"
    assert duplicate.value.status_code == 409
    assert target.read_text(encoding="utf-8") == "researcher content"


def test_binary_preview_is_sandboxed_and_pptx_parser_rejects_other_types(
    tmp_path: Path,
) -> None:
    svg = tmp_path / "figure.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )

    response = asyncio.run(read_binary(str(svg)))
    with pytest.raises(HTTPException) as wrong_type:
        asyncio.run(get_pptx_slides(str(svg)))

    assert response.headers["content-security-policy"].startswith("sandbox")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert wrong_type.value.status_code == 415
