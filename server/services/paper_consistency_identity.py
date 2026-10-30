"""Scientific consistency identity excludes verified print/layout copies of the same authored text."""

from pathlib import Path


def consistency_input_paths(root: Path) -> dict[str, Path]:
    from ..workflows.paper_consistency_invocation import consistency_evidence
    from .paper_derived_figure_binding import _original_print_entrypoint
    from .latex_bundle import _reachable_sources

    paths = {}
    main = _original_print_entrypoint(root) if (root / 'paper/main.tex').is_file() else None
    sources = set(consistency_evidence(root))
    if main is not None:
        sources.update(path for path in _reachable_sources(main, root / 'paper', root)
                       if path.suffix.casefold() in {'.tex', '.bib'})
    for path in sources:
        name = path.relative_to(root).as_posix()
        if name.startswith(('paper/derived-figures/', 'paper/assembly-layout/')) or name == 'paper/main.tex':
            continue
        paths[name] = path
    # Generated copies are validated as exact transformations by the paper gate.
    # Their canonical sources remain bound, even after compilation redirects includes.
    for directory in ('paper/sections', 'paper/tables'):
        paths.update({path.relative_to(root).as_posix(): path for path in (root / directory).glob('*.tex')})
    for name in ('paper/assembly_experiments_figures.tex', 'paper/synthetic_preview_figures.tex'):
        if (root / name).is_file():
            paths[name] = root / name
    if main is not None:
        paths['paper/main.tex'] = main
    return paths
