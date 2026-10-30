"""Describe frozen scenario bounds without asserting population confidence coverage."""

import re


SCOPE_NOTE = ("Recorded interval bounds summarize fixed scenario configurations; "
              "they do not establish population confidence coverage.")
ASSIGNED_RANGE_NOTE = ("These bounds are assigned scenario ranges, not intervals estimated from "
                       "repeat configurations or population samples.")
DIAGNOSTIC_NOTE = ("Shared fields are generator-declared labels only; no data split, "
                   "executed evaluation budget or fair experimental matching was verified.")


def scenario_interval_caption(text: str, *, assigned_bounds: bool = False) -> str:
    text = scenario_evidence_caption(text)
    text = scenario_diagnostic_caption(text)
    if assigned_bounds:
        return assigned_bounds_caption(text)
    if SCOPE_NOTE in text:
        return text
    updated = re.sub(r"(?i)confidence intervals?", "scenario intervals", text)
    if re.search(r"(?i)interval|uncertainty|whisker|\bCI\b", text):
        return updated.rstrip(". ") + ". " + SCOPE_NOTE
    return text


def assigned_bounds_caption(text: str) -> str:
    """Direct constructor endpoints have no confidence level or replicate variation."""
    text = text.replace(SCOPE_NOTE, '')
    text = re.sub(r'Recorded interval bounds summarize fixed scenario configurations; '
                  r'they do not establish population confidence coverage[^.]*\.', '', text)
    text = re.sub(r'(?i)(?:fixed-configuration interval|uncertainty) whiskers', 'assigned scenario-bound whiskers', text)
    text = re.sub(r'(?i)(?:uncertainty|confidence|interval) bands', 'assigned scenario bands', text)
    text = re.sub(r'(?i)95\\?%\s*(?:confidence\s+|scenario\s+)?(?:intervals?|CI)\b', 'assigned scenario bounds', text)
    text = text.strip()
    if ASSIGNED_RANGE_NOTE not in text:
        text = text.rstrip('. ') + '. ' + ASSIGNED_RANGE_NOTE
    return text


def scenario_evidence_caption(text: str) -> str:
    """Name generated fields without upgrading them to measured scientific effects."""
    text = re.sub(r'(?i)task[- ]manifest[- ]selected balanced accuracy or auroc[, ]+task[- ]normalized',
                  'Generator-labelled task-normalized balanced-accuracy-or-AUROC field', text)
    if 'Cross-shift generalization.' in text:
        text = text.replace('Cross-shift generalization.', 'Generated scenario stress labels.')
        text = text.replace('Stress-response trajectories', 'Generated stress-label trajectories')
        text += ' These records do not establish cross-shift generalization or executed perturbation responses.'
    if 'Task calibration and risk coverage.' in text:
        text = text.replace('Task calibration and risk coverage.', 'Generated joint dataset/task risk-coverage rows.')
        text = text.replace('Retained-coverage versus risk curves', 'Joint dataset/task rows of retained coverage and risk')
        text += ' These rows do not establish calibration or a within-population risk-coverage relationship.'
    if re.search(r'(?i)risk', text):
        text = re.sub(r'(?i)uncertainty bands', 'assigned scenario bounds', text)
    return text


def scenario_diagnostic_caption(text: str) -> str:
    """Generated setting labels do not establish executed component interventions."""
    text = re.sub(r"(?i)Objective and architecture ablation", "Generated scenario diagnostic settings", text)
    text = re.sub(r"(?i)Component-removal losses relative to ([^.]+), with uncertainty whiskers\.",
        r"Recorded differences relative to \1, with fixed-configuration interval whiskers. "
        "Labels describe generated settings; they do not establish executed model removals or causal ablations. "
        "A label omitting an evaluation test does not remove a trainable component.", text)
    return re.sub(r"(?i)Each row changes one registered factor while retaining the named controls; effects are relative to ([^.]+)\.",
        r"Rows compare generated diagnostic labels relative to \1; they are not evidence of executed one-factor interventions.", text)


def scenario_table_captions(text: str) -> str:
    from .paper_table_source_labels import selected_table_source_records

    for label, record in selected_table_source_records(text).items():
        original = record["source"]
        caption = record["caption"]
        diagnostic = " & Matched controls & " in original or " & Declared scenario fields & " in original
        interval_table = re.search(r"(?i)interval|uncertainty|whisker|\bCI\b", original)
        if not interval_table and not diagnostic:
            continue
        assigned = label in {'tab:preview-robustness-calibration', 'tab:preview-ablation'}
        updated = scenario_interval_caption(caption, assigned_bounds=assigned) if interval_table else scenario_diagnostic_caption(caption)
        if ASSIGNED_RANGE_NOTE in caption:
            updated = caption
        if interval_table and SCOPE_NOTE not in updated and ASSIGNED_RANGE_NOTE not in updated:
            updated = updated.rstrip(". ") + ". " + SCOPE_NOTE
        if diagnostic and DIAGNOSTIC_NOTE not in updated:
            updated = updated.rstrip(". ") + ". " + DIAGNOSTIC_NOTE
        if diagnostic and not re.search(r'(?i)interval|whisker|\bCI\b|\[\s*[+-]?\d', original.replace(caption, '', 1)):
            updated = updated.replace(', with fixed-configuration interval whiskers.',
                '. This table reports point differences; interval whiskers are shown only in the corresponding figure.')
            updated = updated.replace(' ' + SCOPE_NOTE, '')
        projected = original.replace(caption, updated, 1)
        if assigned and interval_table:
            projected = re.sub(r'(?i)95\\?%\s*(?:CI|interval)\b', 'Assigned bounds', projected)
        if diagnostic:
            projected = projected.replace(" & Matched controls & ", " & Declared scenario fields & ", 1)
        text = text.replace(original, projected, 1)
    return "\n".join(line if line.lstrip().startswith("%") else
                     re.sub(r"(?i)(95\\?%)\s+CI\b", r"\1 interval", line)
                     for line in text.split("\n"))
