from __future__ import annotations

from pathlib import Path

from PIL import Image

from server.services.figure_preview_renderers import (
    render_box_diagram,
    render_drawio_preview,
    render_mermaid_preview,
)


def _assert_valid_preview(path: Path) -> None:
    assert path.is_file()
    with Image.open(path) as image:
        assert image.width >= 1000
        assert image.height >= 450


def test_dependency_free_preview_renderers_create_decodable_images(
    tmp_path: Path,
) -> None:
    box = tmp_path / "box.png"
    mermaid = tmp_path / "mermaid.png"
    drawio = tmp_path / "drawio.png"

    render_box_diagram(
        box,
        title="Scientific workflow",
        labels=["Versioned data", "Mechanism", "Held-out evidence"],
    )
    render_mermaid_preview(
        "flowchart LR\nA[Versioned data] --> B[Held-out evidence]",
        mermaid,
    )
    render_drawio_preview(
        """<mxfile><diagram><mxGraphModel><root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="a" value="Versioned data" vertex="1" parent="1">
          <mxGeometry x="20" y="20" width="180" height="80" as="geometry"/>
        </mxCell>
        <mxCell id="b" value="Held-out evidence" vertex="1" parent="1">
          <mxGeometry x="320" y="20" width="200" height="80" as="geometry"/>
        </mxCell>
        <mxCell id="e" edge="1" source="a" target="b" parent="1"/>
        </root></mxGraphModel></diagram></mxfile>""",
        drawio,
    )

    for path in (box, mermaid, drawio):
        _assert_valid_preview(path)
