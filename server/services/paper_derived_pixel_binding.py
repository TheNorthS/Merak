"""Read-only pixel proof for exact current same-source paper figure projections.

Self-signed output hashes cannot attest scientific pixels. This verifier renders
only the current trusted projection in memory and compares all PDF/PNG/SVG
pixels and PDF text. It never executes supplied source programs, writes files,
starts subprocesses or invokes a model.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .paper_derived_figure_binding import local_path


_MEMORY_ACTIVE: ContextVar[bool] = ContextVar("paper_pixel_proof_memory", default=False)
_AUDIT_INSTALLED = False


def _memory_audit(event: str, arguments: tuple) -> None:
    if not _MEMORY_ACTIVE.get():
        return
    if event == "open":
        _path, mode, flags = arguments
        if (isinstance(mode, str) and any(flag in mode for flag in "wax+")
                or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise PermissionError("Paper pixel binding prohibits persistent writes")
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.rename",
                   "os.link", "os.symlink", "subprocess.Popen", "socket.connect", "socket.getaddrinfo",
                   "socket.gethostbyname"}:
        raise PermissionError("Paper pixel binding prohibits filesystem, process and network execution")


def _begin_memory_guard():
    global _AUDIT_INSTALLED
    if not _AUDIT_INSTALLED:
        sys.addaudithook(_memory_audit)
        _AUDIT_INSTALLED = True
    return _MEMORY_ACTIVE.set(True)


class _MemorySource(ast.NodeTransformer):
    """Remove only the trusted output-directory setup, never scientific calculations."""

    def visit_Expr(self, node: ast.Expr):
        value = node.value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "mkdir"
                and isinstance(value.func.value, ast.Attribute) and value.func.value.attr == "parent"
                and isinstance(value.func.value.value, ast.Name) and value.func.value.value.id == "output"):
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        node = self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "savefig"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "fig"):
            return ast.copy_location(ast.Call(ast.Name("merak_save_memory", ast.Load()),
                                              [ast.Name("fig", ast.Load()), *node.args], node.keywords), node)
        return node


def _matplotlib_variants(code: bytes, source: Path) -> dict[str, bytes]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    captured: dict[str, bytes] = {}

    def save_memory(figure, filename, *args, **kwargs):
        kind = kwargs.pop("format", None) or Path(str(filename)).suffix.lstrip(".").casefold()
        if kind not in {"pdf", "svg", "png"} or kind in captured:
            raise ValueError("Trusted paper source has an unsupported or duplicate variant output")
        buffer = io.BytesIO()
        figure.savefig(buffer, *args, format=kind, **kwargs)
        captured[kind] = buffer.getvalue()

    tree = _MemorySource().visit(ast.parse(code.decode("utf-8")))
    ast.fix_missing_locations(tree)
    prior = set(plt.get_fignums())
    try:
        with matplotlib.rc_context():
            exec(compile(tree, str(source), "exec"), {"__file__": str(source), "__name__": "merak_verified_memory_pixels",
                                                       "merak_save_memory": save_memory})
    finally:
        for number in set(plt.get_fignums()) - prior:
            plt.close(number)
    if set(captured) != {"pdf", "svg", "png"}:
        raise ValueError("Trusted in-memory paper renderer did not produce every canonical variant")
    return captured


def _safe_svg(source: bytes) -> bytes:
    if b"<!ENTITY" in source:
        raise ValueError("Paper SVG pixel proof rejects entity declarations")
    source = re.sub(br'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1\.1//EN"\s+"http://www\.w3\.org/Graphics/SVG/1\.1/DTD/svg11\.dtd">', b"", source)
    if b"<!DOCTYPE" in source:
        raise ValueError("Paper SVG pixel proof rejects untrusted document types")
    root = ET.fromstring(source)
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image"}:
            raise ValueError("Paper SVG pixel proof rejects executable or external artwork")
        for key, value in element.attrib.items():
            name = key.rsplit("}", 1)[-1].casefold()
            if name.startswith("on") or name == "href" and not value.startswith("#"):
                raise ValueError("Paper SVG pixel proof rejects external bindings")
        if "@import" in str(element.text or "").casefold():
            raise ValueError("Paper SVG pixel proof rejects imported styles")
        style = str(element.text or "") + " ".join(element.attrib.values())
        if any(not value.strip(" ' \"").startswith("#") for value in re.findall(r"url\(([^)]+)\)", style, re.IGNORECASE)):
            raise ValueError("Paper SVG pixel proof rejects external style resources")
    return source


def _svg_variants(source: bytes) -> dict[str, bytes]:
    import fitz
    from .svg_variant_conversion import _converter_svg

    safe = _safe_svg(source)
    with fitz.open(stream=_converter_svg(safe), filetype="svg") as svg:
        with fitz.open(stream=svg.convert_to_pdf(), filetype="pdf") as pdf:
            if len(pdf) != 1:
                raise ValueError("Paper SVG projection must render one complete page")
            scale = max(1.5, 1800.0 / max(1.0, pdf[0].rect.width))
            png = pdf[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
            return {"svg": source, "pdf": pdf.tobytes(), "png": png}


def _pdf_facts(raw: bytes) -> tuple[Any, ...]:
    import fitz

    with fitz.open(stream=raw, filetype="pdf") as document:
        if len(document) != 1:
            raise ValueError("Paper variant PDF must have exactly one page")
        page = document[0]
        text = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if str(span.get("text") or "").strip():
                        text.append((span["text"], round(float(span["size"]), 5),
                                     tuple(round(float(value), 4) for value in span["bbox"])))
        pixels = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), colorspace=fitz.csRGB, alpha=False)
        return (round(page.rect.width, 5), round(page.rect.height, 5), tuple(text),
                pixels.width, pixels.height, hashlib.sha256(pixels.samples).hexdigest())


def _png_facts(raw: bytes) -> tuple[Any, ...]:
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        pixels = image.convert("RGBA")
        return pixels.size, hashlib.sha256(pixels.tobytes()).hexdigest()


def _expected_variants(root: Path, packet: dict[str, Any]) -> dict[str, bytes]:
    from .paper_derived_figure_rendering import expected_projection_source
    from .paper_trusted_plot_source import match_trusted_plot

    original = local_path(root, packet["source"])
    projected = local_path(root, packet["source_path"])
    code = expected_projection_source(root, packet)
    actual_source = projected.read_bytes()
    if original.suffix.casefold() in {".svg", ".json"}:
        from .paper_derived_svg_projection import canonical_svg_identity
        same_source = canonical_svg_identity(_safe_svg(actual_source)) == canonical_svg_identity(_safe_svg(code))
    else:
        same_source = actual_source == code
    if not same_source:
        raise ValueError("Paper pixel proof source differs from its exact current trusted projection")
    if original.suffix.casefold() == ".py":
        _name, parameters, _template = match_trusted_plot(original.read_text(encoding="utf-8-sig"))
        data = local_path(root, parameters["data_path"])
        inventory = {item["path"] for item in packet.get("csv_inventory") or [] if isinstance(item, dict)}
        if data.relative_to(root).as_posix() not in inventory:
            raise ValueError("Paper pixel proof source reads undeclared scientific rows")
        return _matplotlib_variants(code, projected)
    if original.suffix.casefold() in {".svg", ".json"}:
        return _svg_variants(code)
    raise ValueError("Paper pixel proof has no supported trusted source producer")


def validate_pixel_binding(root: Path, packet: dict[str, Any]) -> list[str]:
    """Share a successful byte-bound proof within the current gate, never across gates."""
    from .paper_pixel_validation_cache import validate_pixels_once
    return validate_pixels_once(root, packet, lambda: _validate_pixel_binding(root, packet))


def _validate_pixel_binding(root: Path, packet: dict[str, Any]) -> list[str]:
    """Reject changed scientific pixels even when their packet hashes are re-signed."""
    from .paper_derived_figure_rendering import _RENDER_LOCK
    try:
        root = root.resolve(strict=True)
        with _RENDER_LOCK:
            token = _begin_memory_guard()
            try:
                from .paper_matplotlib_memory import readonly_matplotlib_imports
                with readonly_matplotlib_imports(str(root / "paper/derived-figures/.readonly-font-cache")):
                    expected = _expected_variants(root, packet)
                actual = {kind: local_path(root, packet["derived_paths"][kind]).read_bytes() for kind in expected}
                if _pdf_facts(actual["pdf"]) != _pdf_facts(expected["pdf"]):
                    raise ValueError("Derived PDF pixels or scientific text differ from the exact trusted source render")
                if _png_facts(actual["png"]) != _png_facts(expected["png"]):
                    raise ValueError("Derived PNG pixels differ from the exact trusted source render")
                # The exact expected source re-render proves all PNG/PDF outputs.
                # SVG conversion checks prevent a re-signed vector from drifting.
                if _pdf_facts(_svg_variants(actual["svg"])["pdf"]) != _pdf_facts(_svg_variants(expected["svg"])["pdf"]):
                    raise ValueError("Derived SVG pixels or scientific text differ from the exact trusted source render")
            finally:
                _MEMORY_ACTIVE.reset(token)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, ET.ParseError, ImportError) as error:
        return [f"Paper derived pixel binding failed: {error}"]
    return []
