"""gates a workflow engine responsibilities."""

# ruff: noqa: F403, F405
from .engine_context import *

class GatesAMixin:
    @staticmethod
    def _paper_has_unfinished_draft_language(text: str, evidence_mode: str) -> bool:
        patterns = ['lorem ipsum', 'your paper title', 'your abstract here', 'todo\\b', 'insert (?:text|figure|table)', '待补充', '此处填写']
        if evidence_mode != 'synthetic_preview':
            patterns.append('placeholder (?:text|figure|table|content)')
        return bool(re.search('|'.join(patterns), text, flags=re.IGNORECASE))

    @staticmethod
    def _paper_covers_mechanism(mechanism_name: str, method_text: str, semantic_aliases: Optional[list[str]]=None) -> bool:
        normalized_name = ' '.join(str(mechanism_name or '').split()).casefold()
        normalized_method = ' '.join(str(method_text or '').split()).casefold()
        if not normalized_name:
            return True
        if normalized_name in normalized_method:
            return True
        stopwords = {'and', 'with', 'from', 'using', 'based', 'model', 'method'}
        tokens = {token for token in re.findall('[a-z0-9]{4,}', normalized_name) if token not in stopwords}
        aliases = [' '.join(str(value or '').split()).casefold() for value in semantic_aliases or [] if str(value or '').strip()]
        alias_tokens = {token for alias in aliases for token in re.findall('[a-z0-9]{4,}', alias) if token not in stopwords}
        if not tokens:
            if len(alias_tokens) < 2:
                return True
            matched_aliases = sum((token in normalized_method for token in alias_tokens))
            return matched_aliases >= min(4, max(1, (len(alias_tokens) + 2) // 3))
        matched = sum((token in normalized_method for token in tokens))
        if matched >= max(2, (len(tokens) * 2 + 2) // 3):
            return True
        if alias_tokens:
            matched_aliases = sum((token in normalized_method for token in alias_tokens))
            return matched_aliases >= max(2, min(4, (len(alias_tokens) + 2) // 3))
        return False
