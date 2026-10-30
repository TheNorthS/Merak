"""Source-only checks for resources resolved by the packaged backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services.excalidraw_scene_rendering import (
    ExcalidrawSceneError,
    _renderer_command,
    render_scene,
)
from server.services.paper_venue_templates import template_roots


def test_venue_templates_follow_explicit_packaged_skills_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skills = tmp_path / "bundled skills"
    monkeypatch.setenv("MERAK_SKILLS_PATH", str(skills))

    assert template_roots(Path(__file__)) == (skills / "paper-write" / "templates",)


def test_frozen_excalidraw_does_not_probe_system_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import server.services.excalidraw_scene_rendering as rendering

    monkeypatch.setattr(rendering.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        rendering.shutil, "which",
        lambda command: pytest.fail(f"system executable was probed: {command}"),
    )

    with pytest.raises(ExcalidrawSceneError, match="packaged backend"):
        _renderer_command()


@pytest.mark.asyncio
async def test_frozen_excalidraw_preserves_existing_source_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import server.services.excalidraw_scene_rendering as rendering

    monkeypatch.setattr(rendering.sys, "frozen", True, raising=False)
    source = tmp_path / "original.excalidraw"
    source.write_text("existing author-owned scene", encoding="utf-8")

    with pytest.raises(ExcalidrawSceneError, match="packaged backend"):
        await render_scene(
            {"elements": []}, source_path=source,
            svg_path=tmp_path / "figure.svg",
            pdf_path=tmp_path / "figure.pdf",
            png_path=tmp_path / "figure.png",
        )

    assert source.read_text(encoding="utf-8") == "existing author-owned scene"
