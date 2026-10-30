"""Recognize the exact native plot producer and project typography without arbitrary execution."""
import ast
from pathlib import Path

from .scientific_plot_template import SCIENTIFIC_PLOT_TEMPLATE

FIELDS = ('SCIENTIFIC_CONTEXT', 'PUBLICATION_STYLE', 'PLOT_TYPE', 'METRIC', 'CURVE_PLOTS', 'INTERVAL_PLOTS', 'DATA_PATH')


def _match(expected, actual, captures):
    if isinstance(expected, ast.Name) and expected.id in {'__'+name+'__' for name in FIELDS}:
        try:
            value=ast.literal_eval(actual)
        except (ValueError, TypeError):
            return False
        if expected.id in captures and captures[expected.id] != value:
            return False
        captures[expected.id]=value
        return True
    if isinstance(expected, ast.AST):
        return type(expected) is type(actual) and all(_match(getattr(expected,k),getattr(actual,k),captures) for k in expected._fields)
    if isinstance(expected,list):
        return isinstance(actual,list) and len(expected)==len(actual) and all(_match(a,b,captures) for a,b in zip(expected,actual))
    return expected==actual


def match_native_plot(source: str) -> dict | None:
    from .figure_engine import MATPLOTLIB_STYLE_PREAMBLE
    from .scientific_plotting import CURVE_PLOTS, INTERVAL_PLOTS
    tree=ast.parse(source);prefix=ast.parse(MATPLOTLIB_STYLE_PREAMBLE)
    if ast.dump(ast.Module(body=tree.body[:len(prefix.body)],type_ignores=[]))!=ast.dump(prefix):
        return None
    body=tree.body[len(prefix.body):]
    template=ast.parse(SCIENTIFIC_PLOT_TEMPLATE)
    captures={}
    if not _match(template.body,body[:len(template.body)],captures):
        return None
    footer=body[len(template.body):]
    if len(footer)!=5:
        return None
    outputs=[]
    for statement in footer[1:4]:
        try: outputs.append(ast.literal_eval(statement.value.args[0]))
        except (AttributeError, IndexError, ValueError, TypeError):return None
    if any(not isinstance(x,str) or '\n' in x or '\r' in x for x in outputs):return None
    expected=ast.parse('plt.tight_layout()\n'+''.join(
        f'plt.savefig({value!r}, '+('dpi=450, ' if index==2 else '')+'bbox_inches="tight")\n'
        for index,value in enumerate(outputs))+'plt.close()\n')
    if not _match(expected.body,footer,{}):return None
    if captures.get('__CURVE_PLOTS__')!=sorted(CURVE_PLOTS) or captures.get('__INTERVAL_PLOTS__')!=sorted(INTERVAL_PLOTS):return None
    if not isinstance(captures.get('__DATA_PATH__'),str) or not isinstance(captures.get('__PUBLICATION_STYLE__'),dict):return None
    return {'native_literals':captures,'data_path':captures['__DATA_PATH__'],'native_outputs':outputs}


def project_native_plot(source: str, root: Path, output: Path, multiplier: float) -> tuple[str,str,bytes]:
    parameters=match_native_plot(source)
    if parameters is None:raise ValueError('Native plotting source differs from its trusted producer')
    from .paper_trusted_plot_source import _TypographyProjection
    captures=parameters['native_literals'];render=SCIENTIFIC_PLOT_TEMPLATE
    for marker,value in captures.items():render=render.replace(marker,repr(value))
    tree=ast.parse(render)
    for statement in tree.body:
        if isinstance(statement,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='PUBLICATION_STYLE' for x in statement.targets):
            style=dict(captures['__PUBLICATION_STYLE__']);style['font_size']=float(style['font_size'])*multiplier
            statement.value=ast.parse(repr(style),mode='eval').body
    tree=_TypographyProjection(root.resolve(),output.resolve(),multiplier,'native_scientific').visit(tree)
    footer='\n'.join(f'fig.savefig({str(output.with_suffix("."+ext))!r},bbox_inches="tight"'+(',dpi=450)' if ext=='png' else ')') for ext in ('pdf','svg','png'))+'\nplt.close(fig)'
    tree.body.extend(ast.parse(footer).body);ast.fix_missing_locations(tree)
    return ast.unparse(tree)+'\n','native_scientific',SCIENTIFIC_PLOT_TEMPLATE.encode()
