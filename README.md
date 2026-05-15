# argh

A minimal terminal UI for invoking any Python script that uses `argparse`. Each
flag becomes a labelled row; default values render in gray and disappear as
soon as you type; the live `$ ...` line at the bottom shows the exact command
that will run when you hit Enter.

```
greet.py    venv: .venv  (auto)

  --name             world
  --greeting         hello
  --count            1
  --tags             alpha beta
  --output           ·
  --uppercase        ○
  --format           text

  Output format for the greeting.
  choices: text, json, yaml

  $ .venv/bin/python greet.py --count 3 --uppercase

  ↑↓  move    F4  edit    ⏎  run    esc  quit
```

The example above shows every widget kind argh derives from `argparse`:

- `--name`, `--greeting` — string with default, rendered in gray until you type
- `--count` — int with default
- `--tags` — `nargs="+"` list, space-separated default
- `--output` — `default=None`, shown as `·`
- `--uppercase` — `store_true` flag, `○` for off, `●` for on, toggled by any key
- `--format` — `choices=[...]`, the available values appear below the help line

## Install

```bash
pipx install git+https://github.com/borosdenes/argh-tui.git
```

Requires Python 3.10+.

## Usage

```bash
argh path/to/script.py
```

Optional:

```bash
argh path/to/script.py --venv /path/to/venv     # explicit interpreter
```

If `--venv` is omitted, argh looks for a `.venv` next to the script (walking up
toward your home directory). If none is found it falls back to `python3` /
`python` from `PATH`.

### Keyboard

| key                  | action                                                              |
| -------------------- | ------------------------------------------------------------------- |
| `↑` / `↓`            | move between args                                                   |
| `Ctrl-p` / `Ctrl-n`  | same, vim-style                                                     |
| `→`                  | char-by-char fill the default when the value is a prefix of it      |
| any printable key    | toggle a boolean (`○` ↔ `●`)                                        |
| `F4`                 | open the script in `$VISUAL` / `$EDITOR` (fallback: `vi`)           |
| `⏎`                  | run the script with the current values                              |
| `esc`                | revert the focused field's value; on an unmodified field, quit      |
| `Ctrl-c`             | quit                                                                |

After the script exits you're prompted to press Enter to return to argh — your
values are preserved so you can tweak and re-run.

## How it works

To learn a script's arguments without invoking the main work, argh launches the
interpreter in a subprocess with `argparse.ArgumentParser.parse_args`
monkey-patched. The patched `parse_args` serialises the parser's actions as
JSON and exits before the script's real work runs.

> **Security note.** This means argh executes the script's top-level code (its
> imports and any module-level statements) up to the first `parse_args` call.
> Only point argh at scripts you trust — same as running `python script.py`
> would.

> **Startup cost.** Top-level imports also run every time argh launches. For
> scripts that `import torch` (or anything else slow) at module level, expect
> a noticeable delay before the form appears — argh is paying the same import
> cost the script itself would.

## Limitations

- **Subparsers aren't supported.** Scripts that use
  `parser.add_subparsers()` to dispatch between subcommands (`git`-style)
  will only show the top-level parser's arguments — subcommand-specific
  args won't appear. Point argh at the subcommand's underlying module if it
  has one, or wait for proper support.

## License

MIT — see [LICENSE](LICENSE).
