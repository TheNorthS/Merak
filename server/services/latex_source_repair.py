"""Narrow, idempotent repairs for LaTeX and BibTeX source files."""

from __future__ import annotations

import re
from pathlib import Path

import structlog

from ..utils.atomic_write import atomic_write_text, path_lock


logger = structlog.get_logger()


class LatexSourceRepair:
    _SOURCE_PACKAGE_REQUIREMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\\(?:mathbb|mathfrak)\b"), "amsfonts"),
        (re.compile(r"\\(?:checkmark|lesssim|gtrsim|leqslant|geqslant)\b"), "amssymb"),
        (re.compile(r"\\(?:toprule|midrule|bottomrule)\b"), "booktabs"),
        (re.compile(r"\\begin\{tabularx\}"), "tabularx"),
        (re.compile(r"\\multirow\b"), "multirow"),
        (re.compile(r"\\includegraphics\b"), "graphicx"),
    )

    # BibTeX writes these human-readable fields into the generated .bbl as
    # ordinary LaTeX. Bare _, &, %, and # therefore break compilation even
    # though they are valid characters in retrieved metadata. Identifier and
    # URL fields are deliberately excluded because bibliography styles usually
    # render them verbatim or wrap them in \url.
    _BIBTEX_TEXT_FIELDS = frozenset({
        "abstract",
        "address",
        "author",
        "booktitle",
        "edition",
        "editor",
        "institution",
        "journal",
        "keywords",
        "month",
        "note",
        "organization",
        "publisher",
        "school",
        "series",
        "subtitle",
        "title",
    })
    _BIBTEX_TEXT_FIELD_PATTERN = re.compile(
        r"(?im)(?<![\w-])(?P<field>"
        + "|".join(sorted(_BIBTEX_TEXT_FIELDS, key=len, reverse=True))
        + r")\s*=\s*(?P<delimiter>[{\"])",
    )

    @staticmethod
    def _is_escaped(value: str, index: int) -> bool:
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        return bool(backslashes % 2)

    @classmethod
    def _bibtex_value_end(
        cls,
        content: str,
        value_start: int,
        delimiter: str,
    ) -> int | None:
        """Return the closing delimiter index for one braced or quoted value."""
        if delimiter == "{":
            depth = 1
            for index in range(value_start, len(content)):
                char = content[index]
                if cls._is_escaped(content, index):
                    continue
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return index
            return None

        brace_depth = 0
        for index in range(value_start, len(content)):
            char = content[index]
            if cls._is_escaped(content, index):
                continue
            if char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
            elif char == '"' and brace_depth == 0:
                return index
        return None

    @classmethod
    def _escape_bibtex_text_value(cls, value: str) -> tuple[str, int]:
        """Escape LaTeX specials while preserving math and URL command bodies."""
        output: list[str] = []
        escaped_count = 0
        index = 0
        math_delimiter = ""

        while index < len(value):
            command = next(
                (
                    candidate
                    for candidate in ("\\nolinkurl{", "\\url{", "\\path{")
                    if value.startswith(candidate, index)
                ),
                "",
            )
            if command:
                argument_start = index + len(command)
                argument_end = cls._bibtex_value_end(value, argument_start, "{")
                if argument_end is not None:
                    output.append(value[index:argument_end + 1])
                    index = argument_end + 1
                    continue

            if value.startswith("\\ensuremath{", index):
                argument_start = index + len("\\ensuremath{")
                argument_end = cls._bibtex_value_end(value, argument_start, "{")
                if argument_end is not None:
                    output.append(value[index:argument_end + 1])
                    index = argument_end + 1
                    continue

            if not math_delimiter and value.startswith("\\(", index):
                math_delimiter = "\\)"
                output.append("\\(")
                index += 2
                continue
            if not math_delimiter and value.startswith("\\[", index):
                math_delimiter = "\\]"
                output.append("\\[")
                index += 2
                continue
            if math_delimiter in {"\\)", "\\]"} and value.startswith(
                math_delimiter,
                index,
            ):
                output.append(math_delimiter)
                index += len(math_delimiter)
                math_delimiter = ""
                continue

            char = value[index]
            if char == "$" and not cls._is_escaped(value, index):
                token = "$$" if value.startswith("$$", index) else "$"
                if not math_delimiter:
                    math_delimiter = token
                elif math_delimiter == token:
                    math_delimiter = ""
                output.append(token)
                index += len(token)
                continue

            if (
                not math_delimiter
                and char in "_&%#"
                and not cls._is_escaped(value, index)
            ):
                output.append("\\")
                escaped_count += 1
            output.append(char)
            index += 1

        return "".join(output), escaped_count

    @classmethod
    def sanitize_bibtex_content(
        cls,
        content: str,
    ) -> tuple[str, list[dict[str, object]]]:
        """Escape unsafe characters in parsed BibTeX text fields only."""
        pieces: list[str] = []
        repairs: list[dict[str, object]] = []
        cursor = 0
        search_from = 0
        while True:
            match = cls._BIBTEX_TEXT_FIELD_PATTERN.search(content, search_from)
            if not match:
                break
            line_start = content.rfind("\n", 0, match.start()) + 1
            if content[line_start:match.start()].lstrip().startswith("%"):
                search_from = match.end()
                continue
            delimiter = match.group("delimiter")
            value_start = match.end()
            value_end = cls._bibtex_value_end(content, value_start, delimiter)
            if value_end is None:
                search_from = match.end()
                continue
            original = content[value_start:value_end]
            escaped, escaped_count = cls._escape_bibtex_text_value(original)
            if escaped_count:
                pieces.append(content[cursor:value_start])
                pieces.append(escaped)
                cursor = value_end
                repairs.append({
                    "field": match.group("field").lower(),
                    "escaped_characters": escaped_count,
                })
            search_from = value_end + 1
        if not repairs:
            return content, []
        pieces.append(content[cursor:])
        return "".join(pieces), repairs

    def repair_bibliography_text_fields(
        self,
        project_dir: str | Path,
    ) -> list[dict[str, object]]:
        """Atomically repair bibliography copies used by the LaTeX build."""
        project_path = Path(project_dir)
        repaired_files: list[dict[str, object]] = []
        for bib_path in sorted(project_path.glob("*.bib")):
            try:
                original = bib_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            repaired, field_repairs = self.sanitize_bibtex_content(original)
            if not field_repairs or repaired == original:
                continue
            with path_lock(bib_path):
                try:
                    latest = bib_path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError):
                    continue
                if latest != original:
                    continue
                atomic_write_text(bib_path, repaired)
            repaired_files.append({
                "path": str(bib_path),
                "fields": field_repairs,
                "escaped_characters": sum(
                    int(item["escaped_characters"]) for item in field_repairs
                ),
            })
        if repaired_files:
            logger.info(
                "Repaired LaTeX-unsafe BibTeX text fields",
                files=[item["path"] for item in repaired_files],
            )
        return repaired_files

    def repair_common_source_dependencies(
        self,
        project_dir: str | Path,
        main_tex: str = "main.tex",
    ) -> list[str]:
        """Add standard packages required by commands already used in TeX sources.

        This is intentionally narrow: it only adds well-known package imports
        and never rewrites scientific prose, equations, figures, or results.
        """
        project_path = Path(project_dir)
        main_path = project_path / main_tex
        if not main_path.is_file():
            return []

        main_content = main_path.read_text(encoding="utf-8", errors="replace")
        if "\\begin{document}" not in main_content:
            return []

        source_parts: list[str] = []
        for source_path in sorted(project_path.rglob("*.tex")):
            try:
                source_parts.append(
                    source_path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                continue
        source_text = "\n".join(source_parts)

        loaded_packages: set[str] = set()
        for match in re.finditer(
            r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}",
            main_content,
        ):
            loaded_packages.update(
                item.strip() for item in match.group(1).split(",") if item.strip()
            )

        additions: list[str] = []
        for command_pattern, package in self._SOURCE_PACKAGE_REQUIREMENTS:
            if package not in loaded_packages and command_pattern.search(source_text):
                additions.append(package)
                loaded_packages.add(package)
        if not additions:
            return []

        document_index = main_content.index("\\begin{document}")
        package_lines = "".join(f"\\usepackage{{{name}}}\n" for name in additions)
        repaired = (
            main_content[:document_index]
            + package_lines
            + main_content[document_index:]
        )
        atomic_write_text(main_path, repaired)
        return additions



