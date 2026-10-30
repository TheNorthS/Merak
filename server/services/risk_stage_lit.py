"""Collect deterministic lit findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .risk_artifact_support import _finding, _missing, _relative, _text
from .risk_constants import SEARCH_PROTOCOL_RE
from .risk_validator_support import _bib_entries, _citation_keys, _placeholder_excerpt, _retained_reference_mentions

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any, service: Any) -> dict[str, Any]:
    findings: list[dict[str, Any]] = service._search_evidence_findings(root, 'lit', options)
    survey_path = root / 'literature' / 'survey.md'
    bib_path = root / 'literature' / 'references.bib'
    survey = _text(survey_path)
    bib = _text(bib_path)
    if not survey:
        findings.append(_missing('LIT-ART-001', 'literature/survey.md'))
    if not bib:
        findings.append(_missing('LIT-ART-002', 'literature/references.bib'))
        raise _EarlyReturn(findings)
    entries = _bib_entries(bib)
    if not entries:
        findings.append(_finding('LIT-BIB-001', 'blocker', 'citation', 'BibTeX has no parseable entries.', 'references.bib 中没有可解析的文献条目，综述无法追溯来源。', ['literature/references.bib'], 'Repair the BibTeX syntax and include retrieved sources.'))
        raise _EarlyReturn(findings)
    bibliography_placeholder = _placeholder_excerpt(bib)
    if 'workflow_fallback_literature' in bib or bibliography_placeholder:
        findings.append(_finding('LIT-TEMPLATE-002', 'blocker', 'citation', 'BibTeX contains a generated placeholder instead of retrieved bibliographic evidence.', 'references.bib 含有自动生成的占位引用，不能作为检索证据或进入后续论文。', ['literature/references.bib'], 'Remove the placeholder and regenerate the record from an actual retrieved source.'))
    keys = [item['key'] for item in entries]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        findings.append(_finding('LIT-BIB-002', 'blocker', 'citation', f"Duplicate BibTeX keys: {', '.join(duplicates)}", f"BibTeX 引用键重复：{', '.join(duplicates)}；编译和引用映射会产生歧义。", ['literature/references.bib'], 'Assign one stable unique key to every reference.'))
    strategy = service._strategy(root, options)
    survey_limit = max(1, int(strategy.get('literature_max_papers') or 35))
    required_bibliography = service._required_bibliography_count(root, options)
    verified_entries = [item for item in entries if item.get('title') and item.get('author') and item.get('year') and (item.get('traceable') == '1')]
    if len(entries) < required_bibliography:
        findings.append(_finding('LIT-COV-001', 'blocker', 'coverage', f'Only {len(entries)} parseable references were retained; the final manuscript profile requires at least {required_bibliography}.', f'当前仅有 {len(entries)} 条可解析文献，但最终论文画像至少需要 {required_bibliography} 条；若现在放行，论文一致性阶段必然失败。', ['literature/references.bib', 'literature/survey.md', 'paper/PAPER_PROFILE.json'], 'Return to literature retrieval, add relevant records from real search results, and integrate the new sources into the survey before downstream drafting.'))
    elif len(verified_entries) < required_bibliography:
        findings.append(_finding('LIT-COV-002', 'blocker', 'citation', f'Only {len(verified_entries)} of {len(entries)} references have title, author, year, and a stable DOI/URL/arXiv/ISBN identifier; {required_bibliography} verified records are required.', f'现有 {len(entries)} 条记录中只有 {len(verified_entries)} 条具备题名、作者、年份和稳定标识，尚不足以形成 {required_bibliography} 条可核验引用。', ['literature/references.bib'], 'Verify and complete bibliographic metadata from the configured retrieval sources; do not fabricate missing fields.'))
    if len(entries) < survey_limit:
        findings.append(_finding('LIT-COV-003', 'warning', 'coverage', f'The bibliography contains {len(entries)} records; the configured detailed-survey limit is {survey_limit}.', f'当前保留 {len(entries)} 篇文献，低于用户设置的详细综述上限 {survey_limit}；这不是硬性数量门，但应说明检索饱和度和排除理由。', ['literature/survey.md', 'literature/references.bib'], 'Expand the retained set when relevant evidence is still missing, or document saturation and exclusions in the search protocol.'))
    year_from = int(strategy.get('literature_year_from') or 0)
    year_to = int(strategy.get('literature_year_to') or 9999)
    outside = [item['key'] for item in entries if item['year'] and (not year_from <= int(item['year']) <= year_to)]
    if outside:
        findings.append(_finding('LIT-WIN-001', 'warning', 'strategy', f"References outside the configured year window: {', '.join(outside[:12])}", '部分文献超出用户设置的检索年限；若作为经典背景保留，需要在检索协议中说明例外。', ['literature/references.bib', '.merak/research_strategy.json'], 'Remove the records or document why foundational exceptions are retained.'))
    traceable = sum((item['traceable'] == '1' for item in entries))
    if traceable < max(1, len(entries) // 2):
        findings.append(_finding('LIT-TRACE-001', 'warning', 'provenance', 'Fewer than half of BibTeX entries contain DOI, URL, eprint, arXiv, or ISBN metadata.', '超过一半的文献缺少 DOI、URL、eprint、arXiv 或 ISBN，后续引用核验成本较高。', ['literature/references.bib'], 'Add stable identifiers from retrieved metadata.'))
    unknown = sorted(_citation_keys(survey) - set(keys))
    if unknown:
        findings.append(_finding('LIT-CITE-001', 'blocker', 'citation', f"Survey cites unknown BibTeX keys: {', '.join(unknown)}", f"综述引用了 references.bib 中不存在的键：{', '.join(unknown)}。", ['literature/survey.md', 'literature/references.bib'], 'Add verified BibTeX records or correct the citation keys.'))
    downstream_sources = [root / 'ideas' / 'ideas.md', root / 'ideas' / 'novelty_report.md', *sorted((root / 'paper' / 'sections').glob('*.tex'))]
    downstream_unknown: dict[str, list[str]] = {}
    return {key: value for key, value in locals().items() if key in ['bib', 'bib_path', 'bibliography_placeholder', 'downstream_sources', 'downstream_unknown', 'duplicates', 'entries', 'findings', 'keys', 'outside', 'required_bibliography', 'strategy', 'survey', 'survey_limit', 'survey_path', 'traceable', 'unknown', 'verified_entries', 'year_from', 'year_to']}

def _rule_2(downstream_sources: Any, downstream_unknown: Any, entries: Any, findings: Any, keys: Any, root: Any, survey: Any) -> dict[str, Any]:
    for source_path in downstream_sources:
        source_text = _text(source_path)
        if not source_text:
            continue
        missing_keys = sorted(_citation_keys(source_text) - set(keys))
        if missing_keys:
            downstream_unknown[_relative(root, source_path)] = missing_keys
    if downstream_unknown:
        detail = '; '.join((f"{path}: {', '.join(missing)}" for path, missing in downstream_unknown.items()))
        findings.append(_finding('LIT-DOWNSTREAM-CITE-001', 'blocker', 'citation_compatibility', f'Literature revision removed or omitted BibTeX keys still cited by accepted downstream artifacts: {detail}', '文献修订遗漏了已被下游 Idea、新颖性或论文使用的引用键；不能在文献节点通过后再让核心链失效。', ['literature/references.bib'], 'Restore each verified downstream citation record from the prior bibliography or a stable source; preserve existing keys during targeted literature repair.'))
    years_missing = [item['key'] for item in entries if not item.get('year')]
    malformed_years = [item['key'] for item in entries if item.get('year') and (not re.fullmatch('\\d{4}', str(item['year'])))]
    if years_missing or malformed_years:
        findings.append(_finding('LIT-META-001', 'warning', 'provenance', 'Some references have no usable publication year.', '部分文献缺少可用的出版年份，无法可靠核对检索年限和时间边界。', ['literature/references.bib'], 'Resolve the publication year from a stable bibliographic record or mark it as unknown.'))
    missing_bib_fields = [item['key'] for item in entries if not item.get('title') or not item.get('author')]
    if missing_bib_fields:
        findings.append(_finding('LIT-META-002', 'warning', 'provenance', f"References lack title or author metadata: {', '.join(missing_bib_fields[:12])}", '部分参考文献缺少题名或作者，后续引用核验和最近邻比较会变得不可靠。', ['literature/references.bib'], 'Complete title and author fields from the retrieved source metadata.'))
    if survey and (not SEARCH_PROTOCOL_RE.search(survey)):
        findings.append(_finding('LIT-PROTOCOL-001', 'warning', 'research_scope', 'Survey does not expose a reproducible search protocol.', '综述没有明确数据库、检索式、纳入/排除标准或时间窗口，检索结果难以复核。', ['literature/survey.md', '.merak/research_strategy.json'], 'Record the resolved sources, queries, date window, and inclusion/exclusion rules.'))
    if survey and (not re.search('(?:evidence\\s+gap|open\\s+problem|limitation|conflict|证据缺口|未解决|局限|争议)', survey, re.IGNORECASE)):
        findings.append(_finding('LIT-SYNTH-001', 'warning', 'synthesis', 'Survey reads like a catalogue and exposes no limitations or evidence gaps.', '综述目前更像论文列表，没有明确争议、局限或证据缺口，难以支撑后续 Idea。', ['literature/survey.md'], 'Compare assumptions and evidence across works, then state a testable gap.'))
    cited_keys = _retained_reference_mentions(survey, keys)
    uncited = [item['key'] for item in entries if item['key'] not in cited_keys]
    if entries and len(uncited) > len(entries) // 2:
        findings.append(_finding('LIT-CITE-002', 'warning', 'citation', f'More than half of retained references are never cited in the survey: {len(uncited)}/{len(entries)}.', '超过一半已保留文献没有在综述正文中使用，可能是检索结果堆积或证据筛选尚未完成。', ['literature/survey.md', 'literature/references.bib'], 'Either integrate the references into a comparison or remove them from the retained set.'))
    titles = [re.sub('[^a-z0-9]+', ' ', str(item.get('title') or '').casefold()).strip() for item in entries if item.get('title')]
    duplicate_titles = sorted({title for title in titles if title and titles.count(title) > 1})
    if duplicate_titles:
        findings.append(_finding('LIT-DUP-001', 'warning', 'duplication', 'Different BibTeX keys appear to describe the same title.', '不同引用键的题名高度重复，可能重复记录同一论文或预印本版本。', ['literature/references.bib'], 'Merge versions or document why both records are retained.'))
    placeholder = _placeholder_excerpt(survey)
    if placeholder:
        findings.append(_finding('LIT-TEMPLATE-001', 'warning', 'artifact_quality', f'Survey still contains template text: {placeholder}', '综述中仍有模板占位文本，可能没有完成真实检索综合。', ['literature/survey.md'], 'Replace the template fragment with source-backed synthesis or remove it.'))
    return {key: value for key, value in locals().items() if key in ['cited_keys', 'detail', 'duplicate_titles', 'malformed_years', 'missing_bib_fields', 'missing_keys', 'placeholder', 'source_path', 'source_text', 'titles', 'uncited', 'years_missing']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root'], service=state['service']))
        state.update(_rule_2(downstream_sources=state['downstream_sources'], downstream_unknown=state['downstream_unknown'], entries=state['entries'], findings=state['findings'], keys=state['keys'], root=state['root'], survey=state['survey']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
