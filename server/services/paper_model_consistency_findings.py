"""Route explicit failed cross-section review findings to declared section authors."""

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from .manuscript_text import final_consistency_verdict, read_text


def model_consistency_findings(paths: dict[str, Path], specs: Iterable[Any]) -> list[dict[str, Any]]:
    text = read_text(paths["cross_review"])
    if final_consistency_verdict(text) != "FAIL":
        return []
    if _review_inputs_changed(paths):
        return [{'id': 'PAPER-CONSISTENCY-STALE', 'severity': 'blocker', 'category': 'review_freshness',
            'owner_node': 'paper', 'stage_id': 'consistency',
            'target_files': ['paper/CROSS_SECTION_REVIEW.md'], 'legal_write_targets': ['paper/CROSS_SECTION_REVIEW.md'],
            'message': 'Cross-section review sources changed; obtain a fresh independent report before routing prior findings.',
            'plain_message': 'Cross-section review sources changed; a fresh report is required.',
            'validation_issue': 'cross-section reviewer recorded FAIL'}]
    owners = {f"paper/sections/{item.filename}": item.id for item in specs}
    owners["paper/sections/00_abstract.tex"] = "front_matter"
    findings = []
    for block in re.split(r"(?m)(?=^[ \t]*(?:\*\*)?\d+[.)]\s)", text):
        block = re.split(r"(?m)^#{1,6}\s+", block)[0]
        block = re.split(r"(?im)^\s*(?:(?:A|The|One)\s+)?non[- ]blocking\b", block)[0]
        if (not block.strip() or re.search(r"(?i)non[- ]blocking", block.splitlines()[0])
                or "not a request to manufacture missing results" in block.casefold()
                or not re.search(r"(?i)(?:scientific|required|proposed)\s+repair\s*[:*]", block)):
            continue
        if "paper/assembly-layout/paper/sections/" in block:
            # Routing identifies the original author only; current projection
            # acceptance is checked after that author repairs and reassembly runs.
            block = block.replace("paper/assembly-layout/paper/sections/", "paper/sections/")
        runtime = re.search(r"(?im)Responsible runtime artifact\s*\**:\s*\**[ \t]*([^\n]+)", block)
        if runtime and 'paper/tables/synthetic_preview_results.tex' in runtime.group(1):
            identity = hashlib.sha256(block.encode()).hexdigest()[:16]
            findings.append({'id': f'PAPER-RUNTIME-CONSISTENCY-{identity}', 'severity': 'blocker',
                'category': 'publication_table', 'owner_node': 'paper', 'upstream_node': 'paper',
                'stage_id': 'assembly', 'producer_kind': 'deterministic',
                'runtime_operation': 'refresh_paper_runtime_inputs',
                'target_files': ['paper/tables/synthetic_preview_results.tex'], 'legal_write_targets': [],
                'message': 'cross-section reviewer recorded FAIL: ' + block.strip(),
                'validation_issue': 'cross-section reviewer recorded FAIL'})
            continue
        responsible = re.search(r"(?im)Responsible authored sections?\s*\**:\s*\**[ \t]*([^\n]+)", block)
        targets = responsible.group(1) if responsible else block
        for target in dict.fromkeys(re.findall(r"paper/sections/[A-Za-z0-9_.-]+\.tex", targets)):
            if target not in owners:
                continue
            message = f"cross-section reviewer recorded FAIL: {block.strip()}; revise {target}"
            identity = hashlib.sha256(f"{target}:{block}".encode()).hexdigest()[:16]
            findings.append({"id": f"PAPER-MODEL-CONSISTENCY-{identity}", "severity": "blocker",
                "category": "model_consistency", "owner_node": "paper", "upstream_node": "paper",
                "stage_id": owners[target], "target_files": [target], "legal_write_targets": [target],
                "message": message, "plain_message": message, "validation_issue": "cross-section reviewer recorded FAIL",
                "remediation": "Resolve the stated scientific contradiction in the owning source; preserve frozen evidence. "
                               "The independent consistency reviewer must then issue a fresh verdict.",
                "evidence_paths": ["paper/CROSS_SECTION_REVIEW.md", target]})
    return findings


def _review_inputs_changed(paths: dict[str, Path]) -> bool:
    from .manuscript_text import read_owned_state, read_json, sha256
    from .paper_drafting import paper_drafting_service
    if 'root' not in paths:
        return False
    state_path = paths.get('state', paths['root'] / 'paper/DRAFT_STATE.json')
    record = read_owned_state(state_path).get('stages', {}).get('consistency', {})
    previous = record.get('reviewed_input_signature') or record.get('input_signature')
    if not previous:
        return False
    current = paper_drafting_service.stage_input_signature(paths, 'consistency')
    binding = read_json(paths['root'] / '.merak/paper-consistency-binding.json')
    if (binding.get('schema') == 1 and binding.get('report_sha256') == sha256(paths['cross_review'])
            and binding.get('input_signature') == current and binding.get('invocation_id')):
        return False
    return previous != current
