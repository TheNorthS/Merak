"""Print wrapping preserves every character in slash/hyphen scientific conditions."""

import xml.etree.ElementTree as ET

import fitz
import pytest

from server.services.paper_evaluation_svg_layout import reflow_evaluation_svg, _wrap


def test_long_matched_condition_wraps_without_shortening_or_inserting_word_spaces():
    text = "capacity/data/token/tuning-matched"
    raw = ('<svg xmlns="http://www.w3.org/2000/svg" width="500" height="240" viewBox="0 0 500 240">'
           '<g id="eval_group_split"/><g id="eval_publication_labels"/>'
           '<g id="eval_matched_comparisons"><rect x="20" y="20" width="440" height="180"/>'
           f'<text x="38" y="60" font-size="22">{text}</text></g></svg>').encode()
    root = ET.fromstring(reflow_evaluation_svg(raw, 2.0))
    label = next(node for node in root.iter() if node.tag.endswith("}text"))
    assert "".join(label.itertext()) == text
    assert len(label) > 1
    assert all(fitz.get_text_length(child.text, fontsize=44) <= 404 for child in label)
    assert {node.get("id") for node in root.iter() if node.get("id")} == {
        "eval_group_split", "eval_publication_labels", "eval_matched_comparisons"}


def test_unbreakable_overflow_still_fails_instead_of_shrinking_font():
    with pytest.raises(ValueError, match="word wider"):
        _wrap("unbreakableconditionword", 40, 44, False)


def test_side_by_side_text_does_not_add_each_columns_wrap_height():
    raw=('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="260" viewBox="0 0 600 260">'
         '<g id="eval_group_split"/><g id="eval_publication_labels"/><g id="eval_matched_comparisons"/>'
         '<rect x="10" y="30" width="250" height="180"/><rect x="310" y="30" width="250" height="180"/>'
         '<text x="28" y="70" font-size="20">Left condition with several words</text>'
         '<text x="328" y="74" font-size="20">Right condition with several words</text></svg>').encode()
    projected=ET.fromstring(reflow_evaluation_svg(raw,1.4))
    labels=[n for n in projected.iter() if n.tag.endswith('}text')]
    assert abs(float(labels[0].get('y'))-float(labels[1].get('y'))) < 10
    assert float(projected.get('height')) < 330
