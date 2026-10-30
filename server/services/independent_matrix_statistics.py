"""Independent standard-library recomputation of paired-sequence aggregate statistics."""
import csv
import math
import statistics
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=128)
def student_critical(df: int) -> float:
    if df < 1: raise ValueError('Student-t intervals require at least two independent units')
    c=math.exp(math.lgamma((df+1)/2)-math.lgamma(df/2))/math.sqrt(df*math.pi)
    def cdf(x):
        count=2000;step=x/count
        def density(y):return c*(1+y*y/df)**(-(df+1)/2)
        return .5+step*(density(0)+density(x)+sum((4 if i%2 else 2)*density(i*step) for i in range(1,count)))/3
    low,high=0.,100.
    for _ in range(48):
        mid=(low+high)/2
        if cdf(mid)<.975:low=mid
        else:high=mid
    return (low+high)/2


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))


def statistics_for(values: list[float]) -> dict:
    if len(values)<2 or not all(math.isfinite(v) for v in values):raise ValueError('Invalid independent sequence values')
    mean=statistics.fmean(values);sd=statistics.stdev(values);se=sd/math.sqrt(len(values));margin=student_critical(len(values)-1)*se
    return {'mean_delta':mean,'sd_delta':sd,'se_delta':se,'ci95_low':mean-margin,'ci95_high':mean+margin,'n_sequences':len(values)}


def recompute_cell(rows: list[dict]) -> dict:
    required={'baseline','test_sequence_id'}
    if not rows or not required<=rows[0].keys():raise ValueError('Unsupported paired-sequence metric schema')
    metrics=[k.removesuffix('_delta_noisy_minus_control') for k in rows[0] if k.endswith('_delta_noisy_minus_control')]
    if not metrics:raise ValueError('No explicit paired metric columns')
    result={}
    for baseline in sorted({r['baseline'] for r in rows}):
        selected=[r for r in rows if r['baseline']==baseline]
        if len({r['test_sequence_id'] for r in selected})!=len(selected):raise ValueError('Duplicate independent sequence identity')
        for metric in metrics:result[(baseline,metric)]=statistics_for([float(r[metric+'_delta_noisy_minus_control']) for r in selected])
    return result


def compare_summary(cell: dict, raw: list[dict], summary: list[dict], secondary: list[dict]) -> tuple[list[str],int]:
    values=recompute_cell(raw);issues=[];checked=0
    def matches(row):return all(str(row[k])==str(cell[k]) for k in ('condition','axis','seed'))
    for (baseline,metric),expected in values.items():
        selected=[r for r in summary if matches(r) and r['baseline']==baseline and r['metric']==metric]
        if len(selected)!=1:issues.append(f'Nonunique summary row {baseline}/{metric}');continue
        issues.extend(_compare(selected[0],expected));checked+=1
    for row in [r for r in secondary if matches(r)]:
        field=next((k for k in row if k.startswith('difference_in_differences_')), '')
        if not field:raise ValueError('Secondary contrast lacks explicit orientation')
        left,right=field.removeprefix('difference_in_differences_').split('_minus_',1)
        names={r['baseline'] for r in raw}
        left=next((n for n in names if n==left or n.startswith(left+'_')),left)
        metric=row['metric']+'_delta_noisy_minus_control'
        a={r['test_sequence_id']:float(r[metric]) for r in raw if r['baseline']==left}
        b={r['test_sequence_id']:float(r[metric]) for r in raw if r['baseline']==right}
        if not a or a.keys()!=b.keys():raise ValueError('Secondary contrast has unmatched independent units')
        expected=statistics_for([a[k]-b[k] for k in sorted(a)])
        issues.extend(_compare(row,{field:expected['mean_delta'],'ci95_low':expected['ci95_low'],'ci95_high':expected['ci95_high']}));checked+=1
    return issues,checked


def _compare(row: dict, expected: dict) -> list[str]:
    return [f'Independent reconstruction differs: {key}' for key,value in expected.items()
            if key not in row or not math.isclose(float(row[key]),value,rel_tol=1e-5,abs_tol=1e-9)]
