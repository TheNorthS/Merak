"""Export current source with an explicit allowlist, excluding local research and secrets."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'.github', 'merak-skills', 'docs', 'docker', 'electron', 'public',
               'resources', 'scripts', 'server', 'shared', 'src'}
FILES = {'README.md', 'LICENSE', 'AGENTS.md', '.gitignore', '.gitattributes', '.editorconfig',
         '.dockerignore', '.env.example', 'package.json', 'package-lock.json', 'pyproject.toml',
         'requirements.lock', 'electron-builder.yml', 'eslint.config.mjs', 'index.html',
         'postcss.config.mjs', 'tailwind.config.mjs', 'tsconfig.json', 'tsconfig.node.json', 'vite.config.mts'}


def source_files() -> list[Path]:
    """Honor Git ignores and reject local/private files even if accidentally tracked."""
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    files = []
    for name in sorted(set(raw.decode('utf-8').split('\0')) - {''}):
        relative = Path(name)
        if relative.parts[0] not in DIRECTORIES and name not in FILES:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'Linked path cannot be exported: {relative}')
        if (set(relative.parts) & {'node_modules', '__pycache__', '.git', '.merak', 'runtime'}
                or any(part.startswith(('pytest-', '.pytest', 'test-tmp-')) for part in relative.parts)
                or path.name == 'user_settings.json' or path.name.startswith('.env') and name != '.env.example'
                or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pyc', '.key', '.pem', '.pfx', '.p12', '.log'}):
            raise ValueError(f'Private/generated file is tracked: {relative}')
        files.append(path)
    return files


def export_source() -> None:
    """Produce a source-only archive without changing the user's index or commits."""
    files = source_files()
    version = json.loads((ROOT / 'package.json').read_bytes())['version']
    destination = ROOT / 'release' / f'Merak-Source-{version}.zip'
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    required = {'README.md', 'package.json', '.github/workflows/windows-installer.yml'}
    if not required.issubset(manifest):
        raise ValueError('Required source files are missing')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, 'Merak/' + file.relative_to(ROOT).as_posix())
    (destination.parent / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'archive': str(destination), 'files': len(files), 'bytes': destination.stat().st_size}))


if __name__ == '__main__':
    export_source()
