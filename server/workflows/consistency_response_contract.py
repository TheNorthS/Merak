"""Bind a model's explicit verdict to its report without inferring approval from prose."""
import re

SCHEMA = {'type':'object', 'properties': {
    'verdict': {'type':'string', 'enum':['PASS','FAIL']},
    'report': {'type':'string', 'minLength':80}},
    'required':['verdict','report'], 'additionalProperties':False}


def bound_consistency_report(payload: dict) -> str:
    verdict, report = payload.get('verdict'), payload.get('report')
    if verdict not in {'PASS','FAIL'} or not isinstance(report,str):
        raise ValueError('Consistency reviewer must return its explicit PASS/FAIL and report')
    matches=list(re.finditer(r'(?im)^#+\s*Final Consistency Verdict[^\n]*\n',report))
    if len(matches)!=1:
        raise ValueError('Consistency report requires one final-verdict heading')
    start=matches[0].end()
    explicit=re.match(r'\s*(?:\*\*)?(PASS|FAIL)\b',report[start:],re.I)
    if explicit:
        if explicit.group(1).upper()!=verdict:
            raise ValueError('Structured consistency verdict contradicts its report')
        return report
    return report[:start]+verdict+'\n\n'+report[start:]
