from __future__ import annotations

import ast
import json
from pathlib import Path

from server.services.generated_source_repair import generated_source_repair_service


def test_duplicate_module_docstrings_are_repaired_backed_up_and_audited(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "experiments" / "src"
    source_root.mkdir(parents=True)
    broken = '''"""Short module title.
"""Long module documentation.

This body belongs to the module documentation.
"""

def run():
    return 1
'''
    paths = [source_root / name for name in ("data.py", "metrics.py", "models.py", "train.py")]
    for path in paths:
        path.write_text(broken, encoding="utf-8")

    result = generated_source_repair_service.repair_python_sources(tmp_path)

    assert len(result["repaired"]) == 4
    assert result["unresolved"] == []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        ast.parse(content)
        assert content.count('"""Short module title.') == 1
        assert '"""Long module documentation.' not in content
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert len(report["repairs"]) == 4
    for item in report["repairs"]:
        assert (tmp_path / item["backup_path"]).is_file()
        assert item["before_sha256"] != item["after_sha256"]

    repeated = generated_source_repair_service.repair_python_sources(tmp_path)
    assert repeated["repaired"] == []


def test_ambiguous_syntax_error_is_reported_without_guessing(tmp_path: Path) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    source.parent.mkdir(parents=True)
    original = "def broken(:\n    pass\n"
    source.write_text(original, encoding="utf-8")

    result = generated_source_repair_service.repair_python_sources(tmp_path)

    assert result["repaired"] == []
    assert result["unresolved"][0]["path"] == "experiments/src/train.py"
    assert source.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".merak" / "repairs" / "SOURCE_REPAIRS.json").exists()
