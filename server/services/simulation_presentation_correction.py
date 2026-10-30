"""Explicit producer correction of misleading presentation metadata, with immutable evidence archives.

This operation never runs generation and never changes data, scripts or image
variants. It is deliberately not an automatic read-time migration. Callers must
explicitly request the metadata correction on a stopped research project.
"""

import copy
import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock
from .planned_simulation_bindings import load_planned_simulation_binding, rebind_planned_simulation
from .simulation_presentation_policy import simulation_presentation_fields
from .simulation_publication_attestation import (
    MANIFEST_RELATIVE, _assert_inputs_unchanged, _canonical_conflicts, _current_bundle, _registration_updates,
)


def _corrected(payload: dict) -> dict:
    updated = copy.deepcopy(payload)
    updated.update(simulation_presentation_fields(updated))
    for record in updated['figure_files']:
        record.update({key: value for key, value in simulation_presentation_fields(record).items()
                       if key not in {'manuscript_eligible', 'submission_eligible'}})
    if isinstance(updated.get('visual_quality'), dict):
        updated['visual_quality']['uncertainty'] = (
            '95% fixed-configuration scenario intervals or bands; no population coverage claim')
    return updated


def correct_simulation_presentation(root: Path) -> dict:
    """Archive prior manifests and atomically correct only presentation metadata and dependent pins."""
    from .figure_artifacts import figure_artifact_registry
    from .simulation_figure_refresh import _register_current
    from .simulation_table_projection_binding import (
        PUBLICATION_BINDING, CANONICAL_TABLE, verify_simulation_table_projection,
    )

    root = root.resolve(strict=True)
    manifest, registry_path = root / MANIFEST_RELATIVE, root / 'figures/FIGURE_MANIFEST.json'
    with path_lock(registry_path):
        original, payload = manifest.read_bytes(), _current_bundle(root)
        digest = hashlib.sha256(original).hexdigest()
        registry = figure_artifact_registry.load(root / 'figures', strict=True)
        _canonical_conflicts(root, payload['figure_files'])
        _registration_updates(root, payload, registry, digest)
        planned = load_planned_simulation_binding(root, digest, payload['figure_files'])
        proof = verify_simulation_table_projection(root, payload) if (root / CANONICAL_TABLE).is_file() else None
        existing = {entry['id']: entry for entry in registry['figures']}
        targets = [manifest, registry_path, registry_path.with_suffix('.md')]
        if planned:
            targets.append(planned.path)
        if proof is not None:
            targets.append(root / PUBLICATION_BINDING)
        before = {path: path.read_bytes() if path.is_file() else None for path in targets}
        archive = root / '.merak/repair-history/simulation-presentation' / digest
        for path, raw in before.items():
            if raw is not None and not (archive / path.relative_to(root)).exists():
                atomic_write_bytes(archive / path.relative_to(root), raw)
        updated = _corrected(payload)
        _assert_inputs_unchanged(root, payload, original)
        try:
            atomic_write_json(manifest, updated)
            new_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
            _register_current(root, updated, existing, figure_artifact_registry)
            if proof is not None:
                atomic_write_json(root / PUBLICATION_BINDING, {**proof, 'simulation_manifest_sha256': new_hash})
                verify_simulation_table_projection(root, updated)
            if planned:
                plan = rebind_planned_simulation(planned, updated['figure_files'], new_hash)
                plan.update(simulation_presentation_fields(plan))
                entries = {item['id']: item for item in figure_artifact_registry.load(root / 'figures')['figures']}
                plan['figures'] = [entries[item['id']] for item in plan['figures']]
                atomic_write_json(planned.path, plan)
            _assert_inputs_unchanged(root, payload, manifest.read_bytes())
        except BaseException:
            for path, raw in before.items():
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, raw)
            raise
        receipt = {'schema': 1, 'previous_manifest_sha256': digest, 'manifest_sha256': new_hash,
            'data_and_rendered_files_unchanged': True, 'generation_executed': False,
            'changed_paths': [path.relative_to(root).as_posix() for path, raw in before.items()
                              if path.read_bytes() != raw]}
        atomic_write_json(archive / 'receipt.json', receipt)
        return receipt
