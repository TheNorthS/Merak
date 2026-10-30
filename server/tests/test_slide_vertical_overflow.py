from server.services.slide_overflow_validation import slide_overflow_findings


def test_actual_beamer_vertical_overflow_routes_to_source_and_retains_small_warning(tmp_path):
    p=tmp_path/'slides/main.log';p.parent.mkdir()
    p.write_text('Overfull \\vbox (2.82718pt too high) detected at line 124\n'
                 'Overfull \\vbox (17.29175pt too high) detected at line\n228\n')
    found=slide_overflow_findings(tmp_path)
    assert len(found)==1 and found[0]['severity']=='blocker'
    assert found[0]['target_files']==['slides/main.tex']
    assert found[0]['overflow_evidence']==[{'points':17.29175,'line':228}]
    p.write_text('Output written on main.pdf (22 pages).')
    assert slide_overflow_findings(tmp_path)==[]
