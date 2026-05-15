"""Auto-discover a Python interpreter to use for the target script."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Interpreter:
    python: Path
    label: str  # short, human-friendly label for the TUI header (may include "(auto)" / "(system)")
    venv_dir: Path | None = None  # the venv DIR (None when falling back to a system python)


def _venv_python(venv_dir: Path) -> Path | None:
    """Returns the python binary inside a venv dir, or None if it's not a real venv."""
    for rel in ("bin/python", "bin/python3", "Scripts/python.exe"):
        candidate = venv_dir / rel
        if candidate.exists():
            return candidate
    return None


def _walk_up_for_venv(start: Path, stop_at: Path) -> Path | None:
    """Walks up from *start* toward *stop_at*, returning the first directory containing a usable .venv."""
    current = start
    while True:
        venv_dir = current / ".venv"
        if venv_dir.is_dir() and _venv_python(venv_dir):
            return venv_dir
        if current == stop_at or current.parent == current:
            return None
        current = current.parent


def discover(script: Path, explicit_venv: Path | None) -> Interpreter:
    """Resolves an Interpreter for *script*.

    Args:
        script: Path to the script that will be launched. Used as the search anchor.
        explicit_venv: If set, use this venv directly (no auto-discovery).
    """
    if explicit_venv is not None:
        explicit_venv = explicit_venv.expanduser().resolve()
        python = _venv_python(explicit_venv)
        if python is None:
            raise FileNotFoundError(f"--venv: no python found inside {explicit_venv}")
        return Interpreter(python=python, label=str(explicit_venv), venv_dir=explicit_venv)

    script_dir = script.resolve().parent
    home = Path.home()
    venv_dir = _walk_up_for_venv(script_dir, home)
    if venv_dir is not None:
        python = _venv_python(venv_dir)
        if python:
            try:
                label = str(venv_dir.relative_to(Path.cwd())) + "  (auto)"
            except ValueError:
                label = str(venv_dir) + "  (auto)"
            return Interpreter(python=python, label=label, venv_dir=venv_dir)

    for fallback in ("python3", "python"):
        path = shutil.which(fallback)
        if path:
            return Interpreter(python=Path(path), label=f"{fallback}  (system)", venv_dir=None)

    raise FileNotFoundError("No Python interpreter found (.venv, python3, python all missing).")
