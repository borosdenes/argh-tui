# CLAUDE.md

Guidance for working on `argh-tui`.

## What this is

A small TUI that wraps any `argparse`-driven Python script in a form-style
interface. See [README.md](README.md) for the user-facing pitch.

## Layout

```
argh_tui/
├── __main__.py     # `python -m argh_tui` entry
├── cli.py          # argparse CLI: parses `argh <script> [--venv]`
├── venv_utils.py   # auto-discover .venv next to script; fallback to python3
├── extract.py      # subprocess + monkey-patched argparse to extract arg specs
└── tui.py          # textual app: ArghInput, BoolToggle, ArgRow, ArghApp
```

There is no `tests/` directory; behaviour is verified manually in tmux. If you
add tests, prefer `textual.app.App.run_test()` with a `Pilot`.

## How the parts fit

1. `cli.main()` resolves the script and venv, then calls `extract.extract()`.
2. `extract.extract()` runs the user script under a subprocess interpreter with
   `argparse.ArgumentParser.parse_args` monkey-patched. The patched function
   serialises the parser's actions to stdout between sentinel markers and
   `os._exit(0)`s before the script's real work runs. The parent decodes the
   JSON and yields `ArgSpec` dataclasses.
3. `ArghApp` (textual) renders one row per `ArgSpec`. Inputs are `ArghInput`
   (a textual `Input` subclass); booleans get a custom `BoolToggle` widget.
4. `⏎` builds the command from the current widget values and runs it via
   `subprocess.run` inside `with self.suspend():`.

## Aesthetic conventions (don't break these)

- **Light mode only, no chromatic colors.** All foreground/background values
  are explicit hex grays (`#000000`, `#888888`, `#b0b0b0`, `#e4e4e4`, `#ffffff`).
  Don't introduce `$accent`, `$primary`, or any theme-derived color tokens.
- **Highlight bg is `#e4e4e4` (ANSI 254).** Use this exact value for both the
  focused `Input` and `BoolToggle` so they render as the same ANSI cell.
- **Cursor cell is `#000000` / `#ffffff` (inverse).** Selection uses the same.
- **`markup=False` on every Static that shows user-derived strings** (header,
  help, preview, labels). `[fvrf]`-style prefixes in argparse help would
  otherwise be eaten by Rich as markup tags.

## Behavioural conventions

- **One-line widgets only.** All inputs are `height: 1` with `border: none`.
- **Cursor hidden during non-empty selection.** `ArghInput._restart_blink` is
  overridden to set `_cursor_visible = self.selection.is_empty` instead of the
  unconditional `True` — textual's `_restart_blink` runs twice per focus event,
  and the second call would otherwise leak the cursor cell through.
- **`BoolToggle.render` always pads to widget width** with an explicit bg
  style. textual's diff renderer skips cells whose new style is implicit, so
  without the padding the focus highlight lingers after focus moves away.
- **Enter is an app-level priority binding**, not `Input.Submitted`, so it
  fires the same `action_run` regardless of which widget kind is focused.

## Distribution

Versioning lives in `pyproject.toml`. Bump `version = "..."` on every change
you want `pipx upgrade argh-tui` to actually pick up — `pipx` no-ops if the
version string is unchanged.

End-user install (from any machine with Python 3.10+ and pipx):

```bash
pipx install git+https://github.com/borosdenes/argh-tui.git
pipx upgrade argh-tui   # after pushing a version bump
```

Local development:

```bash
pipx install --force ~/Projects/argh-tui   # reinstall after edits
```

## Verifying changes

The TUI rendering is hard to assert from a non-interactive shell. Use tmux to
capture pane content:

```bash
tmux new-session -d -s argh_test -x 130 -y 40 "argh /path/to/script.py"
sleep 2
tmux capture-pane -t argh_test -p           # plain text
tmux capture-pane -t argh_test -p -e        # with ANSI escapes
tmux send-keys -t argh_test C-n             # navigate
tmux kill-session -t argh_test
```

For headless logic checks (focus handling, command building), use
`App.run_test()`:

```python
async with app.run_test() as pilot:
    await pilot.press("ctrl+n", "ctrl+n")
    await pilot.pause()
    print(app._build_command())
```
