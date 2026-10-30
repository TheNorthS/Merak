"""Paper-length planning and compiled-page verification."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json


@dataclass(frozen=True)
class PaperBudget:
    target_pages: int
    tolerance_pages: int
    minimum_pages: int
    maximum_pages: int
    venue: str
    estimated_main_text_words: tuple[int, int]
    section_pages: dict[str, float]
    minimum_figures: int
    minimum_tables: int

    def contains(self, actual_pages: int) -> bool:
        return self.minimum_pages <= actual_pages <= self.maximum_pages

    def distance(self, actual_pages: int) -> int:
        if actual_pages < self.minimum_pages:
            return actual_pages - self.minimum_pages
        if actual_pages > self.maximum_pages:
            return actual_pages - self.maximum_pages
        return 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["estimated_main_text_words"] = list(self.estimated_main_text_words)
        return payload


class PaperBudgetService:
    """Create and verify project-local paper length budgets."""

    budget_relative_path = Path("paper") / "PAPER_BUDGET.json"

    _section_weights = {
        "Abstract": 0.04,
        "Introduction": 0.15,
        "Related Work": 0.10,
        "Method": 0.24,
        "Experiments": 0.22,
        "Results and Discussion": 0.14,
        "Limitations": 0.06,
        "Conclusion": 0.05,
    }

    def normalize(
        self,
        target_pages: int | str | None,
        tolerance_pages: int | str | None = 1,
        venue: str = "",
    ) -> PaperBudget | None:
        try:
            target = int(target_pages or 0)
        except (TypeError, ValueError):
            target = 0
        if target <= 0:
            return None
        target = max(4, min(50, target))
        try:
            tolerance = int(tolerance_pages if tolerance_pages is not None else 1)
        except (TypeError, ValueError):
            tolerance = 1
        tolerance = max(0, min(5, tolerance))

        main_text_pages = max(3.0, target * 0.72)
        section_pages = {
            name: round(main_text_pages * weight, 2)
            for name, weight in self._section_weights.items()
        }
        words_per_page = 650 if venue.strip().lower() in {"cvpr", "acl", "aaai", "ieee"} else 560
        estimated_words = int(main_text_pages * words_per_page)
        return PaperBudget(
            target_pages=target,
            tolerance_pages=tolerance,
            minimum_pages=max(1, target - tolerance),
            maximum_pages=target + tolerance,
            venue=venue.strip() or "unspecified",
            estimated_main_text_words=(int(estimated_words * 0.85), int(estimated_words * 1.15)),
            section_pages=section_pages,
            minimum_figures=2,
            minimum_tables=2,
        )

    def prepare(
        self,
        project_path: str | Path,
        target_pages: int | str | None,
        tolerance_pages: int | str | None = 1,
        venue: str = "",
    ) -> PaperBudget | None:
        budget = self.normalize(target_pages, tolerance_pages, venue)
        if not budget:
            return None
        root = Path(project_path).expanduser().resolve()
        paper_dir = root / "paper"
        paper_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "generated_at": time.time(),
            **budget.to_dict(),
            "policy": {
                "counting": "compiled PDF pages including references and appendices",
                "expansion": "add reproducible method, protocol, evidence analysis, or limitations; never invent results",
                "compression": "remove repetition and tighten presentation without deleting evidence or threats to validity",
            },
        }
        target = root / self.budget_relative_path
        if target.is_file():
            try:
                previous = json.loads(target.read_bytes())
            except (OSError, UnicodeError, json.JSONDecodeError):
                previous = None
            if isinstance(previous, dict) and {key: value for key, value in previous.items() if key != "generated_at"} == {
                key: value for key, value in payload.items() if key != "generated_at"
            }:
                return budget
        atomic_write_json(target, payload)
        return budget

    def load(self, project_path: str | Path) -> PaperBudget | None:
        """Load only the current budget record; do not infer one from a paper plan."""
        root = Path(project_path).expanduser().resolve()
        path = root / self.budget_relative_path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema") != 1 or "target_pages" not in payload:
                return None
            return self.normalize(
                payload.get("target_pages"),
                payload.get("tolerance_pages", 1),
                payload.get("venue", ""),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    @staticmethod
    def prompt(budget: PaperBudget | None) -> str:
        if not budget:
            return ""
        section_lines = "\n".join(
            f"- {name}: about {pages:g} pages"
            for name, pages in budget.section_pages.items()
        )
        low, high = budget.estimated_main_text_words
        return f"""## Compiled Paper Length Soft Target
- Target: approximately {budget.target_pages} compiled PDF pages.
- Preferred range: {budget.minimum_pages}-{budget.maximum_pages} pages, including references and appendices.
- Estimated main-text budget: {low}-{high} words. This estimate is secondary to the compiled page count.
- Venue: {budget.venue}.

Section allocation guide:
{section_lines}

This is planning guidance, not an acceptance gate. A scientifically complete paper may remain outside the preferred range. Do not meet the target with filler, oversized figures, repeated claims, fabricated results, or formatting tricks.
When more space is needed, add reproducible method detail, experimental controls, evidence analysis, and threats to validity.
When less space is needed, remove repetition while preserving claims, evidence, limitations, and reproducibility details."""


paper_budget_service = PaperBudgetService()
