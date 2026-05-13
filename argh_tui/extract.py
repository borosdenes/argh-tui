"""Extracts argparse argument metadata from an arbitrary Python script.

Approach: monkey-patch ``argparse.ArgumentParser.parse_args`` inside a subprocess,
run the script with ``runpy``, and capture the parser's actions as JSON when the
script reaches its ``parse_args`` call.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DUMP_START = "===ARGH_TUI_DUMP_START==="
DUMP_END = "===ARGH_TUI_DUMP_END==="


@dataclass
class ArgSpec:
    """Single argparse argument as understood by the TUI."""
    dest: str
    option_strings: list[str]
    help: str | None
    default: Any
    choices: list[Any] | None
    nargs: Any
    action_class: str
    required: bool
    positional: bool

    @property
    def display_name(self) -> str:
        return self.option_strings[0] if self.option_strings else self.dest

    @property
    def is_bool_flag(self) -> bool:
        return self.action_class in ("_StoreTrueAction", "_StoreFalseAction")

    @property
    def is_list(self) -> bool:
        if self.nargs in ("+", "*"):
            return True
        if isinstance(self.nargs, int) and self.nargs > 1:
            return True
        return self.action_class in ("_AppendAction", "_AppendConstAction", "_ExtendAction")


_EXTRACTOR_SCRIPT = r'''
import argparse, json, os, runpy, sys

_DUMP_START = "{start}"
_DUMP_END = "{end}"


def _safe(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _intercept(parser, *_a, **_kw):
    actions = []
    for action in parser._actions:
        if action.dest == "help":
            continue
        actions.append({{
            "dest": action.dest,
            "option_strings": list(action.option_strings),
            "help": action.help,
            "default": _safe(action.default if action.default is not argparse.SUPPRESS else None),
            "choices": [_safe(c) for c in action.choices] if action.choices else None,
            "nargs": _safe(action.nargs),
            "action_class": type(action).__name__,
            "required": bool(action.required),
            "positional": not action.option_strings,
        }})
    sys.stdout.write("\n" + _DUMP_START + "\n")
    sys.stdout.write(json.dumps(actions))
    sys.stdout.write("\n" + _DUMP_END + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


argparse.ArgumentParser.parse_args = _intercept
argparse.ArgumentParser.parse_known_args = _intercept

target = sys.argv[1]
sys.argv = [target]
runpy.run_path(target, run_name="__main__")
'''


class ExtractionError(RuntimeError):
    pass


def extract(script: Path, python: Path, timeout: int = 60) -> list[ArgSpec]:
    """Runs *script* under *python* with a monkey-patched argparse and returns its arguments."""
    code = _EXTRACTOR_SCRIPT.format(start=DUMP_START, end=DUMP_END)
    proc = subprocess.run(
        [str(python), "-c", code, str(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    combined = proc.stdout + proc.stderr
    start = combined.find(DUMP_START)
    end = combined.find(DUMP_END)
    if start < 0 or end < 0:
        raise ExtractionError(_format_failure(proc, combined))

    payload = combined[start + len(DUMP_START):end].strip()
    try:
        actions = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Argparse dump was not valid JSON: {exc}\n{payload[:500]}") from exc

    return [ArgSpec(**a) for a in actions]


def _format_failure(proc: subprocess.CompletedProcess, combined: str) -> str:
    head = combined.strip().splitlines()[-40:]
    tail = "\n".join(head)
    return (
        f"Could not extract argparse metadata (interpreter exit code {proc.returncode}).\n"
        f"Last output lines:\n{tail}"
    )
