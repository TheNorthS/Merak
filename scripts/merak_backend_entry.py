"""Entry point for the self-contained desktop backend executable.

The packaged application invokes this executable directly; it never needs a
Python interpreter from the user's PATH.  Internal plotting subprocesses use
the same frozen interpreter through ``--run-figure-script``.
"""

from __future__ import annotations

import argparse
import multiprocessing
import runpy
import sys
from pathlib import Path


def _run_figure_script(arguments: list[str]) -> int:
    """Execute a generated plot script in the bundled Python environment."""
    if not arguments:
        raise SystemExit("--run-figure-script requires a .py file")
    script = Path(arguments[0]).resolve()
    if not script.is_file() or script.suffix.lower() != ".py":
        raise SystemExit(f"Figure script does not exist: {script}")
    previous_argv = sys.argv
    try:
        sys.argv = [str(script), *arguments[1:]]
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = previous_argv
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Serve FastAPI, verify the frozen import, or run an internal plot script."""
    multiprocessing.freeze_support()
    argv = list(sys.argv[1:] if arguments is None else arguments)
    if argv and argv[0] == "--run-figure-script":
        return _run_figure_script(argv[1:])

    parser = argparse.ArgumentParser(description="Merak bundled backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--self-check", action="store_true")
    options = parser.parse_args(argv)

    from server.main import app

    if options.self_check:
        from fastapi import FastAPI

        if not isinstance(app, FastAPI):
            raise SystemExit("Bundled backend did not load a FastAPI app")
        print("MERAK_BACKEND_BUNDLE_OK", flush=True)
        return 0

    import uvicorn

    uvicorn.run(
        app,
        host=options.host,
        port=options.port,
        loop="asyncio",
        http="h11",
        ws="websockets",
        lifespan="on",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
