"""A verified print redirect cannot expire science; canonical edits and forged redirects can."""

import hashlib
import json

import pytest

from server.services.paper_drafting import paper_drafting_service


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def projection(root):
    paper=root/'paper';(paper/'sections').mkdir(parents=True)
    section=paper/'sections/03_method.tex';section.write_text('Verified scientific method')
    main=paper/'main.tex';main.write_text(r'\input{sections/03_method}')
    paths=paper_drafting_service.paths(root)
    before=paper_drafting_service.stage_input_signature(paths,'consistency')
    derived=paper/'derived-figures';(derived/'tex/sections').mkdir(parents=True)
    archive=derived/'ORIGINAL_MAIN.tex';archive.write_bytes(main.read_bytes())
    (derived/'tex/sections/03_method.tex').write_bytes(section.read_bytes())
    main.write_text(r'\input{derived-figures/tex/sections/03_method}')
    receipt={'schema':1,'original_main_path':'paper/derived-figures/ORIGINAL_MAIN.tex',
        'original_main_sha256':sha(archive),'sources':[{'original_path':'paper/main.tex','output_path':'paper/main.tex','output_sha256':sha(main)}]}
    (derived/'PRINT_PROJECTION.json').write_text(json.dumps(receipt))
    return paths,before,section,main


def test_print_redirect_keeps_canonical_science_identity(tmp_path):
    paths,before,section,_=projection(tmp_path)
    assert paper_drafting_service.stage_input_signature(paths,'consistency')==before
    section.write_text('Changed scientific method')
    assert paper_drafting_service.stage_input_signature(paths,'consistency')!=before


def test_changed_print_entrypoint_cannot_claim_a_verified_original(tmp_path):
    paths,_before,_section,main=projection(tmp_path)
    main.write_text(main.read_text()+'\nUnbound change')
    with pytest.raises(ValueError,match='differs'):
        paper_drafting_service.stage_input_signature(paths,'consistency')


def test_print_overlay_preserves_generated_figure_entrypoints_and_detects_source_changes(tmp_path):
    paper = tmp_path / 'paper'
    paper.mkdir()
    sources = [paper / 'generated_method_figures.tex', paper / 'generated_evaluation_figures.tex']
    for source in sources:
        source.write_text('Original scientific caption for ' + source.stem)
    main = paper / 'main.tex'
    main.write_text(r'\input{generated_method_figures}\input{generated_evaluation_figures}')
    paths = paper_drafting_service.paths(tmp_path)
    before = paper_drafting_service.stage_input_signature(paths, 'consistency')
    derived = paper / 'derived-figures'
    (derived / 'tex').mkdir(parents=True)
    archive = derived / 'ORIGINAL_MAIN.tex'
    archive.write_bytes(main.read_bytes())
    for source in sources:
        (derived / 'tex' / source.name).write_bytes(source.read_bytes())
    main.write_text(r'\input{derived-figures/tex/generated_method_figures}'
                    r'\input{derived-figures/tex/generated_evaluation_figures}')
    (derived / 'PRINT_PROJECTION.json').write_text(json.dumps({
        'schema': 1, 'original_main_path': 'paper/derived-figures/ORIGINAL_MAIN.tex',
        'original_main_sha256': sha(archive), 'sources': [{'original_path': 'paper/main.tex',
            'output_path': 'paper/main.tex', 'output_sha256': sha(main)}]}))
    assert paper_drafting_service.stage_input_signature(paths, 'consistency') == before
    sources[0].write_text('Changed scientific caption')
    assert paper_drafting_service.stage_input_signature(paths, 'consistency') != before
