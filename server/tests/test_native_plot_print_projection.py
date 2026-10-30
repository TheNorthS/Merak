import ast
from pathlib import Path
import pytest

from server.services.figure_engine import MATPLOTLIB_STYLE_PREAMBLE
from server.services.matplotlib_figure_backend import _executable_code
from server.services.scientific_plotting import build_scientific_plot_script
from server.services.paper_trusted_plot_source import match_trusted_plot, projected_plot_source


def source(root):
    from server.services.publication_figure_labels import concept_labels
    asset={'data_path':'experiments/results/summary.csv','metric':'MAE',
           'publication_labels':concept_labels(['MAE'],namespace='main',kind='metric')}
    code=build_scientific_plot_script(asset,{})
    return _executable_code(code,MATPLOTLIB_STYLE_PREAMBLE,root/'original.pdf',root/'original.svg',root/'original.png')


def test_native_projection_changes_output_and_fonts_but_preserves_data_operations(tmp_path):
    code=source(tmp_path)
    assert match_trusted_plot(code)[0]=='native_scientific'
    projected,kind,_=projected_plot_source(code,tmp_path,tmp_path/'printed',1.3)
    assert kind=='native_scientific' and 'summary.csv' in projected
    assert 'original.pdf' not in projected
    assert str(tmp_path/'printed.pdf') in [n.value for n in ast.walk(ast.parse(projected)) if isinstance(n,ast.Constant)]
    before=ast.parse(code);after=ast.parse(projected)
    def functions(tree):return {x.name: x for x in tree.body if isinstance(x,ast.FunctionDef)}
    assert ast.dump(functions(before)['number'])==ast.dump(functions(after)['number'])
    data=tmp_path/'experiments/results/summary.csv';data.parent.mkdir(parents=True)
    data.write_text('method,mean,ci95_low,ci95_high\nbaseline,0.2,0.1,0.3\n')
    from server.services.paper_derived_figure_rendering import _execute_trusted_plot
    _execute_trusted_plot(projected,tmp_path/'printed.py')
    assert all((tmp_path/f'printed.{ext}').is_file() for ext in ['pdf','svg','png'])
    assert data.read_text().endswith('baseline,0.2,0.1,0.3\n')


@pytest.mark.parametrize('extra',["\nimport subprocess\nsubprocess.run(['bad'])\n",'\nrows=rows[:1]\n'])
def test_native_source_with_extra_operations_remains_untrusted(tmp_path,extra):
    with pytest.raises(ValueError,match='trusted plotting template'):
        match_trusted_plot(source(tmp_path)+extra)
