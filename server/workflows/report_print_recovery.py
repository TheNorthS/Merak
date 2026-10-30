"""Recognize validated runtime print outputs without accepting failed manuscript content."""

import json
from pathlib import Path
import re


def verified_print_refresh(root: Path, before: dict, current: dict) -> bool:
    from ..services.paper_print_projection import RECEIPT, validate_print_projection
    changed = {key for key in before.keys() | current.keys() if before.get(key) != current.get(key)}
    receipt = root / RECEIPT
    if not changed or not receipt.is_file() or validate_print_projection(root):
        return False
    payload = json.loads(receipt.read_bytes())
    allowed = set()
    for row in payload.get('sources', []):
        original = row['original_path']
        if original == 'paper/main.tex' or re.fullmatch(r'paper/assembly_[A-Za-z0-9_]+\.tex', original):
            allowed.update((original, row['output_path']))
    for packet in payload.get('packets', []):
        allowed.update((packet['original_path'], packet['output_path']))
    # Authored sections, scientific inputs, values and code must remain exact.
    return changed <= allowed and all(not key.startswith('paper/sections/') for key in changed)
