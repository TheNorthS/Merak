"""Capture/verify explicitly authorized copy-only correction, without execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


def main() -> int:
    from scripts.scientific_correction_boundary import correction_baseline, digest_file, verify_correction
    from server.utils.atomic_write import atomic_write_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "verify"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state-sha256", default="")
    parser.add_argument("--science-sha256", default="")
    parser.add_argument("--baseline-sha256", default="")
    parser.add_argument("--allow-nonexecuting-correction", action="store_true", required=True)
    options = parser.parse_args()
    root, original = options.snapshot.resolve(strict=True), options.project.resolve(strict=True)
    if root.parent != REPOSITORY or not root.name.startswith("live-verification-106-"):
        raise ValueError("Correction cannot target an arbitrary directory")
    baseline = root / ".merak/authorized-corrections/BASELINE.json"
    if options.operation == "capture":
        if baseline.exists():
            raise ValueError("An existing correction baseline cannot be overwritten")
        result = correction_baseline(root, original, options.run_id,
                                     state_pin=options.state_sha256, science_pin=options.science_sha256)
        atomic_write_json(baseline, result)
        result = {"baseline_path": str(baseline), "baseline_sha256": digest_file(baseline)}
    else:
        result = verify_correction(root, original, baseline, options.baseline_sha256)
        if result["run_id"] != options.run_id:
            raise ValueError("Correction verification has a different run owner")
        atomic_write_json(root / ".merak/authorized-corrections/VERIFICATION.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
