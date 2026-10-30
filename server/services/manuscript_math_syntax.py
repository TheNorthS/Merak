"""Detect incomplete TeX math delimiters before accepting an authored section."""

import re

from .simulation_policy import strip_latex_comments


def math_delimiter_issues(text: str) -> list[str]:
    text = re.sub(r"\\begin\{(verbatim\*?|lstlisting|minted)\}.*?\\end\{\1\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\\verb\*?([^A-Za-z\s]).*?\1", "", text)
    issues = display_math_paragraph_issues(re.sub(r"(?m)^[ \t]*%[^\r\n]*\r?\n", "", text))
    text = strip_latex_comments(text)
    opened = None
    for match in re.finditer(r"(?<!\\)(?:\\\\)*(\$\$?|\\[()[\]])|\n\s*\n", text):
        token = match.group(1)
        line = text.count("\n", 0, match.start()) + 1
        if token is None:
            if opened and opened[0] in {"$", r"\("}:
                issues.append(f"unclosed inline math delimiter {opened[0]} before paragraph break (line {opened[1]})")
                opened = None
            continue
        if opened is None:
            if token in {r"\)", r"\]"}:
                issues.append(f"unmatched math closing delimiter {token} at line {line}")
            else:
                opened = (token, line)
        elif token == {r"\(": r"\)", r"\[": r"\]"}.get(opened[0], opened[0]):
            opened = None
        elif token in {"$", r"\("} and opened[0] in {"$$", r"\["}:
            continue
        else:
            issues.append(f"mismatched math delimiter {token} at line {line}")
    if opened:
        issues.append(f"unclosed math delimiter {opened[0]} at line {opened[1]}")
    return list(dict.fromkeys(issues))


def display_math_paragraph_issues(text: str) -> list[str]:
    """Blank paragraphs terminate TeX math even when the environment delimiters match."""
    pattern = r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}(.*?)\\end\{\1\}"
    issues = []
    for match in re.finditer(pattern, text, re.DOTALL):
        blank = re.search(r"\n[ \t\r]*\n", match.group(2))
        if blank:
            line = text.count("\n", 0, match.start(2) + blank.start()) + 1
            issues.append(f"paragraph break inside {match.group(1)} math environment at line {line}")
    return issues
