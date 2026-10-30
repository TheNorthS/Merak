"""Math scripts require precise context; small chart and numeric prose stay hard."""

from __future__ import annotations

import pytest

from server.services.publication_pdf_fonts import minimum_readable_font_pt, readable_font_findings


class Page:
    def __init__(self, *lines):
        self.lines = lines

    def get_text(self, _mode):
        return {"blocks": [{"lines": [{"spans": line} for line in self.lines]}]}


def _span(text, font, size, box=(10, 20, 35, 30), origin=(10, 28)):
    return {"text": text, "font": font, "size": size, "bbox": box, "origin": origin}


def test_actual_cmr7_named_subscript_is_excluded_only_with_shifted_adjacent_math_base():
    page = Page([_span("L", "CMMI10", 9.9626, (10, 20, 17, 30), (10, 28)),
                 _span("channel", "CMR7", 6.9738, (17, 25, 44, 32), (17, 29.5)),
                 _span("Scientific explanation", "Times-Roman", 10)])
    assert minimum_readable_font_pt(page) == 10
    assert readable_font_findings(page) == []


@pytest.mark.parametrize("glyph", ["∆", "= ∆", "Γ"])
def test_roman_greek_math_base_supports_a_named_superscript(glyph):
    page = Page([_span(glyph, "CMR10", 10, (10, 20, 20, 30), (10, 28)),
                 _span("shift", "CMR7", 7, (20, 17, 40, 24), (20, 24.4)),
                 _span("Explanation", "Times-Roman", 10)])
    assert readable_font_findings(page) == []


def test_ordinary_roman_base_does_not_exempt_small_nearby_prose():
    page = Page([_span("Label", "CMR10", 10, (10, 20, 20, 30), (10, 28)),
                 _span("shift", "CMR7", 7, (20, 17, 40, 24), (20, 24.4))])
    assert readable_font_findings(page)[0]["text"] == "shift"


def test_named_math_operand_and_centered_iid_annotation_are_scripts():
    operand=Page([_span('error','CMR10',10,(10,20,30,30),(10,28)),
        _span('missing','CMR7',7,(30,25,54,32),(30,29.5)),
        _span('−','CMSY10',10,(57,20,64,30),(57,28))])
    # The operator is separated by the script, so use the other operand's adjacent operator.
    operand.lines[0].append(_span('=','CMSY10',10,(3,20,9,30),(3,28)))
    assert readable_font_findings(operand)==[]
    stacked=Page([_span('iid','CMR7',7,(20,12,30,19),(20,18)),
                   _span('∼','CMSY10',10,(20,20,30,30),(20,28))])
    assert readable_font_findings(stacked)==[]


def test_contiguous_named_superscript_after_math_comma_keeps_its_large_base():
    page = Page([_span("S", "CMMI10", 10, (10, 20, 17, 30), (10, 28)),
        _span("MAMP", "CMR7", 7, (17.5, 16, 43, 23), (17.5, 24)),
        _span(",", "CMMI7", 7, (43, 16, 45, 23), (43, 24)),
        _span("shift", "CMR7", 7, (45, 16, 61, 23), (45, 24)),
        _span("Explanation", "Times-Roman", 10)])
    assert readable_font_findings(page) == []


def test_script_chain_does_not_bridge_a_gap_to_small_prose():
    page = Page([_span("S", "CMMI10", 10, (10, 20, 17, 30), (10, 28)),
        _span("MAMP", "CMR7", 7, (17.5, 16, 43, 23), (17.5, 24)),
        _span("tiny prose", "CMR7", 7, (50, 16, 85, 23), (50, 24))])
    assert [item["text"] for item in readable_font_findings(page)] == ["tiny prose"]


def test_named_math_subscript_can_contain_same_baseline_serif_hyphen():
    page = Page([_span("R", "CMMI10", 10, (10, 20, 17, 30), (10, 28)),
        _span("u,", "CMMI7", 7, (17, 24, 24, 31), (17, 29.5)),
        _span("M2", "CMR7", 7, (24, 24, 35, 31), (24, 29.5)),
        _span("-", "NimbusRomNo9L-Regu", 7, (35, 24, 37, 31), (35, 29.5)),
        _span("off", "CMR7", 7, (37, 24, 48, 31), (37, 29.5))])
    assert readable_font_findings(page) == []


@pytest.mark.parametrize("font,text", [("ArialMT", "Calibration error"), ("CMR7", "0.573"),
                                      ("LMRoman8-Regular", "small caption")])
def test_math_neighbor_does_not_exempt_same_baseline_prose_or_numbers(font, text):
    page = Page([_span("L", "CMMI10", 10, (10, 20, 17, 30), (10, 28)),
                 _span(text, font, 6.8, (17, 23, 44, 30), (17, 28))])
    assert minimum_readable_font_pt(page) == 6.8
    assert readable_font_findings(page)[0]["text"] == text


@pytest.mark.parametrize("defect", ["no_math_base", "distant", "missing_geometry", "same_size"])
def test_small_roman_font_name_without_script_geometry_cannot_hide_small_text(defect):
    base = _span("L", "CMMI10", 10, (10, 20, 17, 30), (10, 28))
    small = _span("primary", "CMR7", 7, (17, 25, 44, 32), (17, 30))
    if defect == "no_math_base":
        base["font"] = "Times-Roman"
    elif defect == "distant":
        small["bbox"] = (100, 25, 127, 32)
    elif defect == "missing_geometry":
        small.pop("origin")
    else:
        base["size"] = 7
    assert minimum_readable_font_pt(Page([base, small])) == 7


def test_tex_smallcaps_nominal_eight_points_are_not_a_pdf_unit_rounding_failure():
    bp = 8 * 72 / 72.27
    font = "NimbusRomNo9L-Regu"
    page = Page([_span("S", font, bp / 0.8, (10, 20, 17, 30), (10, 28)),
                 _span("HARED", font, bp, (17, 21, 45, 29), (17, 28))])
    assert minimum_readable_font_pt(page) == 8.0
    assert readable_font_findings(page) == []


@pytest.mark.parametrize("defect", ["chart_font", "ordinary_prose", "numerical_cell", "no_capital", "smaller_text"])
def test_tex_smallcaps_rule_never_lowers_general_eight_point_requirement(defect):
    bp = 8 * 72 / 72.27
    base = _span("S", "NimbusRomNo9L-Regu", bp / 0.8)
    small = _span("HARED", "NimbusRomNo9L-Regu", bp)
    if defect == "chart_font":
        base["font"] = small["font"] = "ArialMT"
    elif defect == "ordinary_prose":
        small["text"] = "Shared structure"
    elif defect == "numerical_cell":
        small["text"] = "0.123"
    elif defect == "no_capital":
        base["text"] = "other text"
    else:
        small["size"] = 7.95
    assert minimum_readable_font_pt(Page([base, small])) < 8
    assert len(readable_font_findings(Page([base, small]))) == 1


def test_small_text_findings_keep_original_bbox_font_and_unrounded_size():
    source = _span("Selective risk", "ArialMT", 5.806700229644775, (12.25, 30.5, 85.7, 38.8))
    assert readable_font_findings(Page([source])) == [{"bbox": [12.25, 30.5, 85.7, 38.8],
        "size_bp": 5.806700229644775, "font": "ArialMT", "text": "Selective risk", "kind": "small_text"}]


def test_math_only_small_spans_do_not_hide_plain_small_text_on_another_line():
    page = Page([_span("x", "CMMI7", 6.9)], [_span("True small label", "ArialMT", 5.8)])
    assert minimum_readable_font_pt(page) == 5.8
    assert readable_font_findings(page)[0]["text"] == "True small label"


def test_stacked_roman_scripts_extracted_as_separate_lines_keep_their_math_base():
    base = _span('M', 'CMMI10', 10, (210,589,223,599), (210,597))
    upper = _span('clean', 'CMR7', 7, (224,588,242,595), (224,593.7))
    lower = _span('stable', 'CMR7', 7, (223,594,244,602), (223,600.2))
    assert readable_font_findings(Page([base, upper], [lower])) == []
    lower['origin'] = (223,610)
    assert readable_font_findings(Page([base, upper], [lower]))[0]['text'] == 'stable'


def test_leading_pdf_space_cannot_hide_the_visible_script_baseline():
    base = _span('M', 'CMMI10', 10, (267,589,277,599), (267,597))
    upper = _span(' clean', 'CMR7', 7, (277,588,296,599), (277,597))
    upper['chars'] = [{'c':' ', 'origin':(277,597), 'bbox':(277,592,278,599)},
                      {'c':'clean', 'origin':(278,593.7), 'bbox':(278,588,296,595)}]
    assert readable_font_findings(Page([base,upper])) == []
    upper['chars'][1]['origin'] = (278,597)
    assert readable_font_findings(Page([base,upper]))


def test_math_base_in_adjacent_pdf_block_requires_same_spatial_script_geometry():
    base = _span('M', 'CMMI10', 10, (210,589,223,599), (210,597))
    lower = _span('stable', 'CMR7', 7, (223,594,244,602), (223,600.2))
    class SplitBlocks:
        def get_text(self, _mode):
            return {'blocks': [{'lines':[{'spans':[s]}]} for s in (base,lower)]}
    assert readable_font_findings(SplitBlocks()) == []
    lower['bbox'] = (280,594,301,602)
    assert readable_font_findings(SplitBlocks())[0]['text'] == 'stable'


@pytest.mark.parametrize('defect', ['', 'lowercase', 'distant', 'different_column', 'numeric'])
def test_wrapped_smallcaps_need_adjacent_aligned_same_heading(defect):
    bp=8*72/72.27;font='NimbusRomNo9L-Regu'
    first=[_span('S',font,bp/0.8,(10,20,17,30),(10,28)),
           _span('HARED',font,bp,(17,21,45,29),(17,28)),
           _span(' TITLE',font,bp,(45,21,75,29),(45,28))]
    last=_span('SCENARIO',font,bp,(10,33,60,41),(10,40))
    if defect=='lowercase':first[1]['text']='ordinary sentence'
    if defect=='distant':last['origin']=(10,70)
    if defect=='different_column':last['bbox']=(100,33,150,41)
    if defect=='numeric':last['text']='0.573'
    findings=readable_font_findings(Page(first,[last]))
    assert any(item['text']==last['text'] for item in findings) is bool(defect)
