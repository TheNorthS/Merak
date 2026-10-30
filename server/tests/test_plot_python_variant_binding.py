import pytest
from server.tests.test_paper_derived_figure_rendering import _entry
from server.services.paper_derived_figure_binding import bound_original_inputs


def test_python_source_variant_is_verified_with_all_rendered_formats(tmp_path):
    entry=_entry(tmp_path)
    meta=entry['metadata']
    meta['rendered_variants']['py']=entry['source_path']
    meta['rendered_variant_sha256']['py']=entry['source_sha256']
    bound,_=bound_original_inputs(tmp_path,entry)
    assert bound[entry['source_path']]==entry['source_sha256']
    meta['rendered_variant_sha256']['py']='0'*64
    with pytest.raises(ValueError,match='canonical Python'):
        bound_original_inputs(tmp_path,entry)


def test_extra_unknown_variant_is_still_rejected(tmp_path):
    entry=_entry(tmp_path);entry['metadata']['rendered_variants']['unknown']=entry['source_path']
    with pytest.raises(ValueError,match='three hash-bound'):
        bound_original_inputs(tmp_path,entry)
