"""Model-assisted paper length revision with reversible source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..agent import ModelRole
from ..agent.engine import AgentEvent, agent_engine
from ..utils.atomic_write import atomic_write_bytes
from .paper_budget import PaperBudget


@dataclass
class TexSnapshot:
    paper_root: Path
    files: dict[Path, bytes]
    protected: dict[Path, bytes | None]


class PaperLengthRevisionService:
    """Revise scientific content while allowing a failed revision to be rolled back."""

    def snapshot(self, project_path: str | Path) -> TexSnapshot:
        root = Path(project_path).expanduser().resolve()
        paper_root = root / "paper"
        files = {
            path.resolve(): path.read_bytes()
            for path in paper_root.rglob("*.tex")
            if path.is_file()
        }
        protected_paths = [
            paper_root / "PAPER_PLAN.md",
            paper_root / "PAPER_BUDGET.json",
            # Kept for reversible edits of projects created before the budget
            # artifact was separated from the manuscript plan.
            paper_root / "PAPER_PLAN.json",
            paper_root / "EVIDENCE_SNAPSHOT.json",
            paper_root / "tables" / "TABLE_MANIFEST.json",
            root / "figures" / "FIGURE_MANIFEST.json",
        ]
        protected = {
            path.resolve(): path.read_bytes() if path.exists() else None
            for path in protected_paths
        }
        return TexSnapshot(paper_root=paper_root, files=files, protected=protected)

    def protected_unchanged(self, snapshot: TexSnapshot) -> bool:
        for path, expected in snapshot.protected.items():
            actual = path.read_bytes() if path.exists() else None
            if actual != expected:
                return False
        return True

    def restore(self, snapshot: TexSnapshot) -> None:
        current = {
            path.resolve()
            for path in snapshot.paper_root.rglob("*.tex")
            if path.is_file()
        }
        for path in current - set(snapshot.files):
            path.unlink(missing_ok=True)
        for path, content in snapshot.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, content)
        for path, content in snapshot.protected.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(path, content)

    async def revise(
        self,
        project_path: str | Path,
        budget: PaperBudget,
        actual_pages: int,
        on_event: Optional[Callable[[AgentEvent], Awaitable[None]]] = None,
    ) -> str:
        root = Path(project_path).expanduser().resolve()
        direction = "expand" if actual_pages < budget.minimum_pages else "compress"
        agent_engine._tool_definitions or self._ensure_tools()
        system_prompt = f"""You are a scientific paper editor performing a constrained length revision.
The current compiled paper has {actual_pages} pages. The accepted range is
{budget.minimum_pages}-{budget.maximum_pages} pages, with a target of {budget.target_pages}.

Edit the existing LaTeX sources in place. Preserve all claim qualifiers, citations, equations,
evidence provenance, limitations, figure/table references, and reproducibility details.
Never invent a result, citation, dataset, baseline, sample count, or statistical claim.
Do not manipulate margins, font sizes, line spacing, image scaling, or bibliography formatting to
hit the target. Do not add filler or repeat claims.

If expanding, add only substantive method derivation, protocol details, controls, failure analysis,
evidence interpretation, and threats to validity that are grounded in project artifacts.
If compressing, remove repetition and tighten prose while retaining the scientific contract.
Use Read/Glob/Grep before Edit or Write and finish with a short change summary."""
        session = agent_engine.create_session(system_prompt=system_prompt, role=ModelRole.EXECUTOR)
        session.project_path = str(root)
        return await agent_engine.run(
            session_id=session.id,
            user_message=(
                f"{direction.capitalize()} the paper at {root / 'paper' / 'main.tex'} to the accepted "
                f"compiled range {budget.minimum_pages}-{budget.maximum_pages}. Read "
                f"{root / 'paper' / 'PAPER_PLAN.md'}, {root / 'paper' / 'PAPER_BUDGET.json'}, "
                f"and {root / 'paper' / 'EVIDENCE_SNAPSHOT.json'} first."
            ),
            on_event=on_event,
            tools=["Read", "Edit", "Write", "Glob", "Grep"],
            max_tokens=4096,
            partial_stream_timeout_seconds=120.0,
        )

    @staticmethod
    def _ensure_tools() -> None:
        from ..agent.tools import register_all_tools

        register_all_tools()


paper_length_revision_service = PaperLengthRevisionService()
