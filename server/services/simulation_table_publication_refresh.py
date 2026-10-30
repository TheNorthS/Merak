"""Refresh paper-owned simulation tables at their producer before reader checks.

The owner prepares an exact current projection from authenticated frozen inputs
and commits only LaTeX/proof/registration. Existing scientific data, figure
outputs and generation manifests remain immutable; failed commits restore all.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile

from ..utils.atomic_write import atomic_write_bytes, path_lock


def refresh_simulation_publication_tables(root: Path) -> bool:
    """Commit current paper projections before downstream portfolio validation."""
    from .paper_evidence import PaperEvidence
    from .paper_submission_tables import _synthetic_preview_entries
    from .paper_table_transaction import _read_current_manifest, commit_prepared_table_bundle
    from .simulation_figure_portfolio import simulation_contribution_type
    from .simulation_table_publication import prepare_simulation_table_publication

    root = root.resolve()
    if not (root / "experiments/results/simulated/SIMULATION_MANIFEST.json").is_file():
        return False
    with ExitStack() as locks:
        for relative in ("paper/tables/TABLE_MANIFEST.json", "paper/tables/synthetic_preview_results.tex"):
            locks.enter_context(path_lock(root / relative))
        contribution = simulation_contribution_type(root)
        update = prepare_simulation_table_publication(root, contribution)
        if not update.files:
            return False
        manifest_relative = "paper/tables/TABLE_MANIFEST.json"
        manifest_path = root / manifest_relative
        manifest_baseline = {manifest_relative: manifest_path.read_bytes()} if manifest_path.is_file() else {}
        previous = _read_current_manifest(manifest_path)
        # Existing non-simulation table ownership is preserved by the ordinary bundle transaction.
        entries = [entry for entry in previous.get("tables") or []
                   if entry.get("evidence_status") != "synthetic_preview"]
        source_hashes = dict(update.source_hashes)
        from .paper_artifacts import bind_table_manifest_hashes
        from .retained_table_input_closure import retained_table_input_hashes

        retained = {"schema": 3, "tables": entries}
        _bound, issues, _changed = bind_table_manifest_hashes(root, retained)
        if issues:
            raise ValueError("Existing unrelated publication tables changed: " + "; ".join(issues))
        for relative, digest in retained_table_input_hashes(root, entries).items():
            if relative in source_hashes and source_hashes[relative] != digest:
                raise ValueError("Publication table inputs changed during preparation: " + relative)
            source_hashes[relative] = digest
        baseline = {name: (root / name).read_bytes() for name in update.files if (root / name).is_file()}
        baseline.update(manifest_baseline)
        selected = json.loads((root / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8-sig"))
        # Registration only: no method/design/scientific snapshot is inferred by this typed adapter.
        evidence = PaperEvidence(root, str((selected.get("publication") or {}).get("title") or selected.get("title") or ""),
            "", "", "", "", "", "",
            asset_plan={"evidence_mode": "synthetic_preview"},
            selected_idea=selected)
        transactions = root / ".merak/transactions"
        transactions.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="publication-tables-", dir=transactions) as directory:
            stage = Path(directory)
            for relative, raw in update.files.items():
                atomic_write_bytes(stage / relative, raw)
            entries.extend(_synthetic_preview_entries(evidence, stage / "paper/tables"))
            commit_prepared_table_bundle(root, stage, entries, source_hashes=source_hashes,
                owned_paths=set(update.files), canonical_baseline=baseline)
    return True
