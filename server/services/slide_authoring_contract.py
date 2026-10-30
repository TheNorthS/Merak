"""One contract for the loaded talk author and its concrete delivery artifacts."""

import re
from pathlib import Path


SUPPORT_FILES = ('SLIDE_OUTLINE.md', 'speaker_notes.md', 'TALK_SCRIPT.md')


def loaded_talk_instruction() -> str:
    return """
## Current loaded talk-author operation
You are already executing the /paper-talk owner skill. A missing execution
receipt is runtime bookkeeping: do not call Skill(paper-talk) to create one.
Complete the actual outputs below using Read/Write/Edit. If the optional
sub-skill budget is exhausted, continue directly with those file tools; it
does not prevent authoring. Do not stop at a status report or ask to continue.
Produce 15–20 meaningful Beamer frames, SLIDE_OUTLINE.md, speaker_notes.md,
and TALK_SCRIPT.md under slides/. Preserve existing useful material and the
read-only paper/experimental evidence. Runtime creates compile/hash/status
records. Never write those records yourself. Scientific words such as
synthetic, deterministic, unexecuted and pending are necessary evidence
descriptions and are allowed; only administrative badges/watermarks are banned.
The current manuscript's qualified implementation and evidence scope controls
all slide claims; outdated speaker notes must be corrected to that scope.
"""


def talk_delivery_findings(root: Path, text: str) -> list[dict]:
    """Compiled old decks cannot satisfy missing current talk outputs."""
    from .risk_artifact_support import _finding
    issues = []
    frames = len(re.findall(r'\\begin\{frame\}', re.sub(r'(?m)(?<!\\)%.*$', '', text)))
    if not 15 <= frames <= 20:
        issues.append(_finding('PPT-TALK-FRAMES', 'blocker', 'slides',
            f'Current talk contract requires 15–20 frames; found {frames}.',
            f'当前演讲交付要求15–20页，实际为{frames}页。', ['slides/main.tex'],
            'Complete the loaded paper-talk author using paper-grounded content; do not invoke the owner skill recursively.'))
    missing = [f'slides/{name}' for name in SUPPORT_FILES
               if not (root/'slides'/name).is_file() or not (root/'slides'/name).read_text(encoding='utf-8-sig').strip()]
    if missing:
        issues.append(_finding('PPT-TALK-SUPPORT', 'blocker', 'slides',
            'Talk delivery is missing outline, notes or script: ' + ', '.join(missing),
            '演讲交付缺少大纲、逐页备注或完整讲稿。', missing,
            'Write each missing paper-grounded artifact directly with file tools; preserve the source paper.'))
    return issues
