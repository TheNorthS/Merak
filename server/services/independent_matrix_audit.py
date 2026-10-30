"""Runtime-owned independent re-aggregation and byte audit; never execute project scripts."""
import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json
from .independent_matrix_statistics import read_rows, compare_summary

REPORT='.merak/quality/independent-matrix-audit.json'


def audit_current_matrix(root: Path) -> dict | None:
    root=root.resolve();selection=root/'experiments/results/accepted_matrix.json'
    if not selection.is_file():return None
    spec=json.loads((root/'experiments/RUN_SPEC.json').read_bytes())
    matrix=json.loads(selection.read_bytes())
    if matrix.get('run_spec_sha256') != _sha(root/'experiments/RUN_SPEC.json'):
        return None
    outputs=(spec.get('outputs') or {}).get('aggregate_files') or []
    csvs=[(p,read_rows(_local(root,p))) for p in outputs if str(p).endswith('.csv')]
    summaries=[(p,r) for p,r in csvs if r and {'baseline','metric','mean_delta','n_sequences','sd_delta','se_delta','ci95_low','ci95_high'}<=r[0].keys()]
    if len(summaries)!=1:return None
    summary_path,summary=summaries[0]
    secondary=[r for _,rows in csvs for r in rows if any(k.startswith('difference_in_differences_') for k in r)]
    issues=[];checked=0;hashes={}
    from .execution_cell_binding import expected_jobs
    from ..workflows.managed_output_validation import managed_output_issues
    for job in expected_jobs(spec,matrix['matrix_id']):
        issues.extend(managed_output_issues(root,spec,root/'.merak/experiments'/job/'run.json'))
    for relative in ['experiments/RUN_SPEC.json','experiments/results/accepted_matrix.json',*outputs]:
        hashes[relative]=_sha(_local(root,relative))
    for cell in matrix['cells']:
        directory=_local(root,cell['output_dir'],directory=True)
        provenance=directory/'provenance.json';record=json.loads(provenance.read_bytes())
        hashes[provenance.relative_to(root).as_posix()]=_sha(provenance)
        for name,digest in record['result_file_sha256'].items():
            path=(directory/name).resolve()
            if not path.is_relative_to(directory):raise ValueError('Cell provenance path escapes its cell')
            actual=_sha(path);hashes[path.relative_to(root).as_posix()]=actual
            if actual!=digest:issues.append(f'Hash mismatch: {path.relative_to(root)}')
        raw_path=directory/'sequence_metrics.csv'
        if raw_path.relative_to(root).as_posix() not in hashes:raise ValueError('Raw sequence metrics not hash-bound')
        found,count=compare_summary(cell,read_rows(raw_path),summary,secondary)
        issues.extend(f"{cell['cell_id']}: {issue}" for issue in found);checked+=count
    payload={'schema':1,'producer':'independent-runtime-statistics','matrix_id':matrix['matrix_id'],
        'passed':not issues,'cells_checked':len(matrix['cells']),'statistical_rows_checked':checked,
        'input_sha256':hashes,'issues':issues,'summary_source':summary_path,
        'scope':'Independent recomputation from paired sequence metrics plus final-byte provenance checks; no project script executed.'}
    for relative,digest in hashes.items():
        if _sha(_local(root,relative))!=digest:raise ValueError('Audit input changed during validation')
    atomic_write_json(root/REPORT,payload)
    if issues:raise ValueError('Independent matrix audit failed: '+'; '.join(issues[:8]))
    return payload


def _local(root: Path, relative: str, *, directory=False) -> Path:
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or (not path.is_dir() if directory else not path.is_file()):
        raise ValueError('Audit input is missing or outside project: '+relative)
    return path


def _sha(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):digest.update(part)
    return digest.hexdigest()
