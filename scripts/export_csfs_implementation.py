"""Export the explicitly authorized tested implementation to a new project copy."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


def main() -> int:
    from server.services.csfs_implementation_export import export_csfs_reference

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--protocol-test-receipt", type=Path, required=True)
    parser.add_argument("--allow-nonexecuting-implementation-export", action="store_true", required=True)
    options = parser.parse_args()
    result = export_csfs_reference(options.source, options.protocol_test_receipt, REPOSITORY)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
