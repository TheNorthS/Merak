"""Re-signed PDF/PNG/SVG metadata cannot replace exact source-generated pixels."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from server.services.paper_derived_pixel_binding import validate_pixel_binding
from server.services.paper_derived_figure_rendering import derive_paper_figure
from server.tests.test_paper_derived_figure_rendering import _entry, _placement


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _resign(root: Path, packet: dict, kind: str) -> None:
    path = root / packet["derived_paths"][kind]
    packet["derived_sha256"][kind] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / packet["provenance_path"]).write_bytes(json.dumps(packet).encode("utf-8"))


def test_safe_svg_keeps_internal_markers_but_rejects_external_styles():
    from server.services.paper_derived_pixel_binding import _safe_svg
    internal = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10" marker-end="url(#arrow)"/></svg>'
    assert _safe_svg(internal) == internal
    with pytest.raises(ValueError, match="external style resources"):
        _safe_svg(internal.replace(b"url(#arrow)", b"url(https://foreign.invalid/image.svg)"))


@pytest.mark.parametrize("svg", [False, True])
@pytest.mark.asyncio
async def test_current_source_generated_pixels_verify_entirely_in_memory_without_writes(tmp_path, svg):
    from matplotlib.figure import Figure
    original_savefig = Figure.savefig
    entry = _entry(tmp_path, svg=svg)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    before = _files(tmp_path)
    assert validate_pixel_binding(tmp_path, packet) == []
    assert _files(tmp_path) == before
    assert Figure.savefig is original_savefig


@pytest.mark.parametrize("kind", ["pdf", "png", "svg"])
@pytest.mark.asyncio
async def test_wrong_scientific_pixels_remain_blocking_after_hash_and_packet_resigning(tmp_path, kind):
    entry = _entry(tmp_path, svg=True)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    path = tmp_path / packet["derived_paths"][kind]
    if kind == "pdf":
        import fitz
        with fitz.open(path) as document:
            document[0].insert_text((40, 210), "Fabricated outcome 0.999", fontsize=22)
            altered = document.tobytes()
        path.write_bytes(altered)
    elif kind == "png":
        from PIL import Image, ImageDraw
        with Image.open(path) as source:
            image = source.convert("RGBA")
        ImageDraw.Draw(image).rectangle((30, 30, 160, 80), fill="red")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        path.write_bytes(buffer.getvalue())
    else:
        path.write_bytes(path.read_bytes().replace(b"Frozen evaluation endpoint", b"Fabricated value 0.999"))
        packet["derived_sha256"]["source"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _resign(tmp_path, packet, kind)
    before = _files(tmp_path)
    issues = validate_pixel_binding(tmp_path, packet)
    assert issues and any("source" in issue or "pixels" in issue for issue in issues)
    assert _files(tmp_path) == before


@pytest.mark.asyncio
async def test_trusted_source_is_recomputed_instead_of_executing_replaced_derived_code(tmp_path):
    entry = _entry(tmp_path)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    source = tmp_path / packet["source_path"]
    marker = tmp_path / "forbidden.txt"
    source.write_bytes(source.read_bytes() + f"\nopen({str(marker)!r},'w').write('executed')\n".encode("utf-8"))
    _resign(tmp_path, packet, "source")
    assert validate_pixel_binding(tmp_path, packet)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_svg_external_artwork_cannot_become_valid_by_resigning_derived_output(tmp_path):
    entry = _entry(tmp_path, svg=True)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    svg = tmp_path / packet["derived_paths"]["svg"]
    before = svg.read_bytes()
    document = ET.fromstring(before)
    image = ET.SubElement(document, "{http://www.w3.org/2000/svg}image")
    image.set("href", "https://foreign.invalid/image.png")
    changed = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    assert changed != before and b"https://foreign.invalid/image.png" in changed
    svg.write_bytes(changed)
    _resign(tmp_path, packet, "svg")
    assert validate_pixel_binding(tmp_path, packet)


@pytest.mark.asyncio
async def test_scoped_pixel_reuse_rechecks_actual_resigned_png(tmp_path, monkeypatch):
    import fitz
    from server.services import paper_derived_pixel_binding as pixels
    from server.services.paper_pixel_validation_cache import pixel_validation_scope

    entry = _entry(tmp_path, svg=True)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    original, calls = pixels._expected_variants, []
    def observe(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(pixels, '_expected_variants', observe)
    with pixel_validation_scope():
        assert validate_pixel_binding(tmp_path, packet) == []
        assert validate_pixel_binding(tmp_path, packet) == []
        assert len(calls) == 1
        with fitz.open() as document:
            document.new_page().insert_text((30, 30), 'Forged plot')
            (tmp_path / packet['derived_paths']['png']).write_bytes(document[0].get_pixmap().tobytes('png'))
        _resign(tmp_path, packet, 'png')
        assert validate_pixel_binding(tmp_path, packet)
        assert len(calls) == 2
