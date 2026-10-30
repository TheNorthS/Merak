"""Namespace registry churn cannot alter scientific SVG projection identity."""

import xml.etree.ElementTree as ET

import pytest

from server.services.paper_derived_svg_projection import canonical_svg_identity, scaled_svg_typography


SOURCE = (b'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="240" viewBox="0 0 1200 240">'
          b'<g id="scientific-object" data-role="matched-control"><path d="M10 20 L100 20" stroke="black"/>'
          b'<text x="50" y="80" font-size="22">Frozen scientific source label</text></g></svg>')


def test_namespace_prefix_change_preserves_exact_expanded_source_identity(monkeypatch):
    registry = dict(ET._namespace_map)
    monkeypatch.setattr(ET, "_namespace_map", registry.copy())
    ET.register_namespace("paperfixture", "http://www.w3.org/2000/svg")
    before = scaled_svg_typography(SOURCE, 1.2)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    after = scaled_svg_typography(SOURCE, 1.2)
    assert before != after
    assert canonical_svg_identity(before) == canonical_svg_identity(after)


@pytest.mark.parametrize("old,new", [(b"source label", b"invented label"), (b'x="50"', b'x="55"'),
                                     (b"M10 20 L100 20", b"M10 20 L99 20"),
                                     (b"matched-control", b"different-science"),
                                     (b"scientific-object", b"foreign-object")])
def test_canonical_namespace_comparison_does_not_ignore_scientific_text_or_geometry(old, new):
    changed = SOURCE.replace(old, new)
    assert changed != SOURCE
    assert canonical_svg_identity(changed) != canonical_svg_identity(SOURCE)


def test_same_local_tag_with_foreign_namespace_is_not_a_current_svg_identity():
    changed = SOURCE.replace(b"http://www.w3.org/2000/svg", b"https://foreign.invalid/semantic")
    assert canonical_svg_identity(changed) != canonical_svg_identity(SOURCE)


def test_verbatim_tail_and_text_spaces_are_not_normalized_away():
    changed = SOURCE.replace(b"Frozen scientific", b"Frozen  scientific").replace(b"</text>", b"</text>extra-tail")
    assert canonical_svg_identity(changed) != canonical_svg_identity(SOURCE)


def test_every_attribute_including_external_binding_is_preserved_in_identity():
    changed = SOURCE.replace(b'<g id=', b'<g href="file:///foreign" id=')
    assert canonical_svg_identity(changed) != canonical_svg_identity(SOURCE)


@pytest.mark.asyncio
async def test_successful_svg_packet_reuses_without_redraw_after_namespace_registry_switch(tmp_path, monkeypatch):
    from server.tests.test_paper_derived_figure_rendering import _entry, _placement
    from server.services import paper_derived_figure_rendering as producer

    monkeypatch.setattr(ET, "_namespace_map", dict(ET._namespace_map))
    ET.register_namespace("paperfixture", "http://www.w3.org/2000/svg")
    entry = _entry(tmp_path, svg=True)
    placement = _placement(tmp_path, entry)
    packet = await producer.derive_paper_figure(tmp_path, entry, placement)
    source = tmp_path / packet["source_path"]
    before = source.read_bytes()
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    assert not producer.validate_derived_figure(tmp_path, packet)
    monkeypatch.setattr(producer, "_render_candidate", lambda *_args: pytest.fail("Namespace spelling cannot force a redraw"))
    assert await producer.derive_paper_figure(tmp_path, entry, placement) == packet
    assert source.read_bytes() == before
