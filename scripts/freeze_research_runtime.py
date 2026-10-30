"""Archive an executable, credential-free validation runtime in a new directory."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

REPOSITORY = Path(__file__).resolve().parents[1]
DIRECTORIES = ("server", "merak-skills", "shared", "scripts", "resources", "public")
EXCLUDED = {"tests", "__pycache__", "node_modules", ".git", ".merak", "output"}
SECRET_NAMES = {".env", "user_settings.json", "credentials.json", "secrets.json"}


def freeze(destination: Path) -> dict:
    destination = destination.resolve()
    if not destination.is_relative_to(REPOSITORY / "output") or destination.exists():
        raise ValueError("Runtime archive requires a new directory under output/")
    from scripts.export_source import source_files
    files = [path for path in source_files()
             if path.relative_to(REPOSITORY).parts[0] in DIRECTORIES
             and not set(path.relative_to(REPOSITORY).parts) & EXCLUDED]
    files.extend(REPOSITORY / name for name in ("pyproject.toml", "requirements.lock", "package.json"))
    hashes = {}
    for path in sorted(files):
        relative = path.relative_to(REPOSITORY)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    payload = {"schema_version": 1, "source_id": identity, "files": hashes}
    (destination / "SOURCE_MANIFEST.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"source_id": identity, "files": len(hashes), "runtime": str(destination)}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(REPOSITORY))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(freeze(parser.parse_args().output)))
