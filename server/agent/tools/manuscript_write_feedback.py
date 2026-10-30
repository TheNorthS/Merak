"""Return measured prose length after author writes, using the acceptance counter."""

from pathlib import Path


def manuscript_write_feedback(path: Path, content: str) -> str:
    if path.suffix.lower() != '.tex' or path.parent.name != 'sections':
        return ''
    from ...services.manuscript_text import word_count
    return ('\nMeasured manuscript word count: ' + str(word_count(content))
            + '. This uses the acceptance validator counter; do not estimate length yourself. '
              'Check this value against the stage requirement and revise before finishing. '
              'This measurement alone is not acceptance.')
