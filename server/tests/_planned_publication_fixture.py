"""Explicit publication inputs and finite renderer boundary for local planning tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def author_publication_fixture(
    root: Path, *, method_name: str, comparators: Sequence[str],
    public_mechanisms: Sequence[str] | None = None,
    public_evaluations: Sequence[str] | None = None,
    contribution_type: str = "objective_mechanism",
) -> None:
    """Author current source fields in a fixture, without scientific completion claims."""
    path = root / "ideas/SELECTED_IDEA.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "title": method_name, "hypothesis": "The named conditions may differ at the declared endpoint.",
        "claims": [{"id": "C1", "statement": "The named conditions may differ at the declared endpoint."}],
        "mechanisms": [],
    }
    selected["schema"] = 2
    selected["publication"] = {
        "language": "en", "title": selected.get("title") or method_name,
        "method_name": method_name, "contribution_type": contribution_type,
        "comparator_names": list(comparators),
    }
    mechanisms = selected.get("mechanisms") or []
    if public_mechanisms is not None and len(public_mechanisms) != len(mechanisms):
        raise ValueError("Test mechanism public names must match the source record inventory")
    for index, mechanism in enumerate(mechanisms):
        public = public_mechanisms[index] if public_mechanisms is not None else str(mechanism.get("name") or "")
        if not public or any("\u3400" <= character <= "\u9fff" for character in public):
            raise ValueError("Test publication names must be explicitly authored, not guessed translations")
        mechanism.update(publication_name=public,
                         publication_description=mechanism.get("description") or f"Declared role of {public}.",
                         publication_evaluation=(public_evaluations[index] if public_evaluations is not None
                                                 else f"Compare the declared {public} condition with its matched reference."))
    for claim in selected.get("claims") or []:
        claim.setdefault("publication_statement", claim.get("statement") or "Compare the declared endpoint.")
    path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")


async def render_finite_fixture(script: Path) -> tuple[bool, str]:
    """Write finite valid variants without executing the generated plotting script."""
    import fitz
    from PIL import Image, ImageDraw

    document = fitz.open()
    page = document.new_page(width=600, height=360)
    page.insert_text((36, 40), "Finite local renderer fixture", fontsize=14)
    page.draw_rect(fitz.Rect(80, 140, 230, 280), fill=(0.1, 0.5, 0.6))
    page.draw_rect(fitz.Rect(350, 180, 500, 280), fill=(0.8, 0.4, 0.1))
    document.save(script.with_suffix(".pdf"))
    document.close()
    script.with_suffix(".svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="360"><rect x="80" y="140" width="150" height="140" fill="#198099"/><rect x="350" y="180" width="150" height="100" fill="#c65d21"/></svg>', encoding="utf-8")
    image = Image.new("RGB", (1200, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 280, 460, 560), fill="#198099")
    draw.rectangle((700, 360, 1000, 560), fill="#c65d21")
    image.save(script.with_suffix(".png"))
    return True, ""
