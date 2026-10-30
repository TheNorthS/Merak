import pytest
from server.services.independent_matrix_statistics import statistics_for, recompute_cell, compare_summary


def test_independent_stats_and_did_detect_changed_summary():
    raw=[{'baseline':b,'test_sequence_id':str(i),'MAE_delta_noisy_minus_control':str(v)}
         for b,values in [('linear',[1,2,3]),('persistence',[2,4,6])] for i,v in enumerate(values)]
    cell={'condition':'c','axis':'a','seed':1}
    summary=[{**cell,'baseline':b,'metric':m,**s} for (b,m),s in recompute_cell(raw).items()]
    did=statistics_for([-1,-2,-3])
    secondary=[{**cell,'metric':'MAE','difference_in_differences_linear_minus_persistence':did['mean_delta'],
                'ci95_low':did['ci95_low'],'ci95_high':did['ci95_high']}]
    assert compare_summary(cell,raw,summary,secondary)==([],3)
    summary[0]['mean_delta']=99
    assert compare_summary(cell,raw,summary,secondary)[0]


def test_duplicate_independent_units_are_rejected():
    rows=[{'baseline':'a','test_sequence_id':'same','MAE_delta_noisy_minus_control':'1'}]*2
    with pytest.raises(ValueError,match='Duplicate'):recompute_cell(rows)


def test_student_interval_matches_known_three_observation_value():
    s=statistics_for([1,2,3])
    assert s['mean_delta']==2 and s['sd_delta']==1
    assert s['ci95_high']==pytest.approx(4.4841377,abs=1e-5)
