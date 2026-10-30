"""Design tables distinguish evaluation requirements from trainable modules."""

from server.services.paper_table_projection import method_components_table_tex, METHOD_ELEMENTS_CAPTION


def test_method_table_preserves_cells_but_does_not_imply_each_element_is_removable():
    rows = [{"component":"Shift-specific mechanism test", "function":"Matched ablations distinguish mechanisms.",
        "evaluation":"Estimate paired shift-minus-within-domain contrasts."}]
    text = method_components_table_tex(rows)
    assert METHOD_ELEMENTS_CAPTION in text
    assert "Evaluation tests are not trainable components" in text
    assert "Method element & Declared design intent & Evaluation protocol" in text
    assert "conditional on the stated implementation and pairing assumptions" in text
    assert "does not independently verify their realization" in text
    assert "Execution evidence is reported separately in the results" in text
    assert "comparisons, assumptions and prerequisites" in text
    assert "current implementation and full attribution contrasts" not in text
    assert all(value in text for value in rows[0].values())
