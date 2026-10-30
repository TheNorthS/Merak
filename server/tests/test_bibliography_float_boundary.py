from server.services.paper_manuscript_assembly import _bibliography


def test_generated_bibliography_drains_pending_scientific_floats_first(tmp_path):
    paper=tmp_path/'paper';paper.mkdir()
    (paper/'references.bib').write_text('@article{key,title={Title}}')
    text=_bibliography({'paper':paper},'plainnat')
    assert text.index(r'\clearpage') < text.index(r'\bibliography{references}')
    assert r'\bibliographystyle{plainnat}' in text
