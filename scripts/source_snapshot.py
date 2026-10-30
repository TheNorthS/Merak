"""Create a reviewable source baseline without committing user changes or copying secrets."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("src", "server", "electron", "shared", "scripts", "merak-skills", "docs", ".github", "docker")
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".mts", ".json", ".md", ".yml", ".yaml", ".toml", ".css", ".html", ".sh", ".conf", ".tex"}
ROOT_FILES = ("package.json", "package-lock.json", "pyproject.toml", "requirements.lock", "AGENTS.md",
              "README.md", "tsconfig.json", "tsconfig.node.json", "eslint.config.mjs", "vite.config.mts",
              "electron-builder.yml", ".gitignore", ".gitattributes", ".dockerignore")


def main() -> None:
    files = {ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()}
    for name in SOURCE_ROOTS:
        for path in (ROOT / name).rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix not in SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if any(part.startswith((".pytest", "pytest-", "__pycache__")) for part in relative.parts):
                continue
            if path.name in {"user_settings.json", ".env"}:
                continue
            files.add(path)
    output = ROOT / "output/code-audit-107-repair"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output / "source-baseline.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(ROOT).as_posix()
            content = path.read_bytes()
            manifest[relative] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            archive.writestr(relative, content)
    (output / "source-baseline.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Source baseline: {len(manifest)} files; local credentials, databases and generated previews excluded")


if __name__ == "__main__":
    main()
