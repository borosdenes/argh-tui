"""argh CLI entry point."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from argh_tui import extract, venv_utils
from argh_tui.tui import ArghApp


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="argh",
        description="TUI for invoking Python scripts with argparse.",
    )
    parser.add_argument("script", type=Path, help="The Python script to invoke.")
    parser.add_argument(
        "--venv",
        type=Path,
        default=None,
        help="Path to venv directory. If omitted, .venv is auto-discovered "
             "(script dir, walking up; fallback: python3 / python).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    script = args.script.expanduser().resolve()
    if not script.exists():
        sys.stderr.write(f"argh: script not found: {script}\n")
        return 1

    try:
        interpreter = venv_utils.discover(script, args.venv)
    except FileNotFoundError as exc:
        sys.stderr.write(f"argh: {exc}\n")
        return 1

    try:
        specs = extract.extract(script, interpreter.python)
    except extract.ExtractionError as exc:
        sys.stderr.write(f"argh: {exc}\n")
        return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write("argh: script took too long to load (timeout).\n")
        return 1

    if not specs:
        sys.stderr.write(f"argh: no argparse arguments detected in {script}\n")
        return 1

    app = ArghApp(
        script=script,
        python=interpreter.python,
        venv_dir=interpreter.venv_dir,
        specs=specs,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
