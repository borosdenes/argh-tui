"""Compact-list TUI: argparse args as rows with gray-placeholder defaults."""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
from pathlib import Path

from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.suggester import SuggestFromList
from textual.widgets import Input, Static

from argh_tui.extract import ArgSpec


NAV_KEYS = frozenset({
    "up", "down", "left", "right",
    "enter", "escape",
    "ctrl+p", "ctrl+n", "ctrl+c",
    "tab", "shift+tab",
})

HIGHLIGHT_BG = "#e4e4e4"  # ANSI 254 — same for Input and BoolToggle


def _format_default(spec: ArgSpec) -> str:
    if spec.default is None:
        return "·"
    if isinstance(spec.default, list):
        return " ".join(str(x) for x in spec.default)
    return str(spec.default)


def _suggester_for(spec: ArgSpec) -> SuggestFromList | None:
    if spec.default is None or spec.is_bool_flag:
        return None
    return SuggestFromList([_format_default(spec)])


class BoolToggle(Static):
    """Focusable circle: ○ for False, ● for True. Any non-nav key toggles."""

    can_focus = True

    class Toggled(Message):
        pass

    DEFAULT_CSS = """
    BoolToggle {
        width: 1fr;
        height: 1;
        color: #b0b0b0;
        background: #ffffff;
    }
    BoolToggle.-modified { color: #000000; }
    BoolToggle:focus { background: #e4e4e4; color: #888888; }
    BoolToggle.-modified:focus { background: #e4e4e4; color: #000000; }
    """

    def __init__(self, default: bool):
        super().__init__(classes="value", expand=True)
        self._default = default
        self._state = default

    @property
    def state(self) -> bool:
        return self._state

    @property
    def modified(self) -> bool:
        return self._state != self._default

    def reset(self) -> None:
        self._state = self._default
        self._refresh()
        self.post_message(self.Toggled())

    def on_mount(self) -> None:
        self._refresh()

    def on_resize(self, event) -> None:
        self.refresh()

    def watch_has_focus(self, focused: bool) -> None:
        self._refresh()

    def toggle(self) -> None:
        self._state = not self._state
        self._refresh()
        self.post_message(self.Toggled())

    def render(self) -> Text:
        char = "●" if self._state else "○"
        width = max(self.size.width, 1) if self.size else 1
        text = Text()
        if self.has_focus:
            text.append(char, style="#ffffff on #000000")
            fill_style = "on #e4e4e4"
        else:
            char_style = "#000000 on #ffffff" if self.modified else "#b0b0b0 on #ffffff"
            text.append(char, style=char_style)
            fill_style = "on #ffffff"
        # Always pad to widget width with explicit bg — otherwise textual leaves
        # previously-rendered cells (including the focus highlight) in place.
        if width > 1:
            text.append(" " * (width - 1), style=fill_style)
        return text

    def _refresh(self) -> None:
        self.set_class(self.modified, "-modified")
        self.refresh()

    def on_key(self, event) -> None:
        if event.key in NAV_KEYS:
            return
        self.toggle()
        event.stop()


class ChoicePicker(Static):
    """Focusable cycler for `choices=...` args: left/right move through values."""

    can_focus = True

    class Toggled(Message):
        pass

    DEFAULT_CSS = """
    ChoicePicker {
        width: 1fr;
        height: 1;
        color: #b0b0b0;
        background: #ffffff;
    }
    ChoicePicker.-modified { color: #000000; }
    ChoicePicker:focus { background: #e4e4e4; color: #888888; }
    ChoicePicker.-modified:focus { background: #e4e4e4; color: #000000; }
    """

    def __init__(self, choices: list[str], default: str | None):
        super().__init__(classes="value", expand=True)
        self._choices = choices
        self._default_index = choices.index(default) if default in choices else None
        self._index = self._default_index  # None means "no choice yet"

    @property
    def value(self) -> str:
        return "" if self._index is None else self._choices[self._index]

    @property
    def modified(self) -> bool:
        return self._index != self._default_index

    def reset(self) -> None:
        self._index = self._default_index
        self._refresh()
        self.post_message(self.Toggled())

    def on_mount(self) -> None:
        self._refresh()

    def on_resize(self, event) -> None:
        self.refresh()

    def watch_has_focus(self, focused: bool) -> None:
        self._refresh()

    def cycle(self, direction: int) -> None:
        if self._index is None:
            self._index = 0 if direction > 0 else len(self._choices) - 1
        else:
            self._index = (self._index + direction) % len(self._choices)
        self._refresh()
        self.post_message(self.Toggled())

    def render(self) -> Text:
        char = self.value if self._index is not None else "·"
        width = max(self.size.width, 1) if self.size else 1
        text = Text()
        if self.has_focus:
            fill_style = "on #e4e4e4"
            char_style = f"{'#000000' if self.modified else '#888888'} on #e4e4e4"
        else:
            fill_style = "on #ffffff"
            char_style = f"{'#000000' if self.modified else '#b0b0b0'} on #ffffff"
        text.append(char, style=char_style)
        # Pad to widget width with explicit bg — same reason as BoolToggle.render.
        if width > len(char):
            text.append(" " * (width - len(char)), style=fill_style)
        return text

    def _refresh(self) -> None:
        self.set_class(self.modified, "-modified")
        self.refresh()

    def on_key(self, event) -> None:
        if event.key == "left":
            self.cycle(-1)
            event.stop()
        elif event.key == "right":
            self.cycle(1)
            event.stop()


class ArghInput(Input):
    """Input variant that:

    1. Hides the cursor cell while the selection is non-empty, so re-focusing a
       populated field doesn't add a visible cell one past the selected text.
    2. Maps the right arrow to char-by-char default fill when the cursor is at
       the end of a value that is a prefix of the default.
    """

    BINDINGS = [
        Binding("right", "smart_right", show=False),
    ]

    def __init__(self, *args, default_value: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._default_value = default_value

    def watch_selection(self, selection) -> None:
        self._cursor_visible = selection.is_empty

    def _restart_blink(self) -> None:
        # textual's default sets _cursor_visible = True unconditionally, which
        # leaks the cursor cell through on re-focuses of a populated field
        # (select_on_focus re-sets the selection to its previous range, so
        # watch_selection doesn't refire). Honor the current selection here so
        # the cursor stays hidden whenever there's a non-empty selection.
        self._cursor_visible = self.selection.is_empty
        if self.cursor_blink and self._blink_timer:
            self._blink_timer.reset()

    def action_smart_right(self) -> None:
        val = self.value
        default = self._default_value
        if (
            self.selection.is_empty
            and self.cursor_position == len(val)
            and default
            and default.startswith(val)
            and len(val) < len(default)
        ):
            self.value = val + default[len(val)]
            self.cursor_position = len(self.value)
            return
        self.action_cursor_right()


class ArgRow(Horizontal):
    def __init__(self, spec: ArgSpec, label_width: int):
        super().__init__()
        self.spec = spec
        self._label_width = label_width
        self.label = Static(spec.display_name, classes="label", markup=False)
        self.value_widget: ArghInput | BoolToggle | ChoicePicker
        if spec.is_bool_flag:
            self.value_widget = BoolToggle(default=bool(spec.default))
        elif spec.choices and not spec.is_list:
            self.value_widget = ChoicePicker(
                choices=[str(c) for c in spec.choices],
                default=str(spec.default) if spec.default is not None else None,
            )
        else:
            default_str = _format_default(spec) if spec.default is not None else ""
            self.value_widget = ArghInput(
                placeholder=_format_default(spec),
                suggester=_suggester_for(spec),
                default_value=default_str,
                classes="value",
            )
            self.value_widget.cursor_blink = False

    def compose(self) -> ComposeResult:
        yield self.label
        yield self.value_widget

    def on_mount(self) -> None:
        self.label.styles.width = self._label_width

    @property
    def modified(self) -> bool:
        w = self.value_widget
        if isinstance(w, (BoolToggle, ChoicePicker)):
            return w.modified
        return w.value != ""

    def reset(self) -> None:
        w = self.value_widget
        if isinstance(w, (BoolToggle, ChoicePicker)):
            w.reset()
        else:
            w.value = ""


class ArghApp(App):
    CSS = """
    Screen { background: #ffffff; color: #000000; }

    #header  { padding: 1 2 0 2; color: #000000; background: #ffffff; }
    #help    { padding: 0 2; color: #888888; background: #ffffff; margin-top: 1; height: auto; }

    #bottom  { dock: bottom; height: auto; background: #ffffff; }
    #preview { padding: 0 2; color: #888888; background: #ffffff; }
    #footer  { padding: 0 2; color: #888888; background: #ffffff; margin-top: 1; margin-bottom: 1; }

    VerticalScroll {
        height: auto;
        max-height: 1fr;
        padding: 1 2 0 2;
        scrollbar-size: 0 0;
        background: #ffffff;
    }

    ArgRow      { height: 1; background: #ffffff; }
    .label      { color: #000000; background: #ffffff; }

    Input {
        background: #ffffff;
        border: none;
        padding: 0;
        height: 1;
        color: #000000;
    }
    Input:focus {
        background: #e4e4e4;
        background-tint: #e4e4e4 0%;
        border: none;
    }
    Input > .input--placeholder { color: #b0b0b0; background: #ffffff; text-style: none; }
    Input:focus > .input--placeholder { color: #888888; background: #e4e4e4; text-style: none; }
    Input > .input--suggestion { color: #b0b0b0; background: #ffffff; text-style: none; }
    Input:focus > .input--suggestion { color: #888888; background: #e4e4e4; text-style: none; }
    Input > .input--cursor { background: #000000; color: #ffffff; }
    Input > .input--selection { background: #000000; color: #ffffff; }
    """

    BINDINGS = [
        Binding("up", "focus_previous", show=False, priority=True),
        Binding("down", "focus_next", show=False, priority=True),
        Binding("ctrl+p", "focus_previous", show=False, priority=True),
        Binding("ctrl+n", "focus_next", show=False, priority=True),
        Binding("f4", "edit", show=False, priority=True),
        Binding("enter", "run", show=False, priority=True),
        Binding("escape", "escape", show=False, priority=True),
        Binding("ctrl+c", "quit", show=False, priority=True),
    ]

    def __init__(
        self,
        script: Path,
        python: Path,
        venv_label: str,
        specs: list[ArgSpec],
    ) -> None:
        super().__init__()
        self.theme = "textual-light"
        self.script_path = script
        self.python_path = python
        self.venv_label = venv_label
        self.specs = specs
        self.label_width = max((len(s.display_name) for s in specs), default=12) + 2
        self.rows: list[ArgRow] = []

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self.script_path.name}    venv: {self.venv_label}",
            id="header",
            markup=False,
        )
        with VerticalScroll(id="rows"):
            for spec in self.specs:
                row = ArgRow(spec, self.label_width)
                self.rows.append(row)
                yield row
        yield Static("", id="help", markup=False)
        with Container(id="bottom"):
            yield Static("", id="preview", markup=False)
            yield Static("↑↓  move    F4  edit    ⏎  run    esc  quit", id="footer", markup=False)

    def on_mount(self) -> None:
        # VerticalScroll is focusable by default (textual lets you focus
        # scrollables); exclude it so up/down cycles only through the rows.
        self.query_one("#rows", VerticalScroll).can_focus = False
        if self.rows:
            self.rows[0].value_widget.focus()
        self._refresh()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_preview()

    def on_bool_toggle_toggled(self, event: BoolToggle.Toggled) -> None:
        self._update_preview()

    def on_choice_picker_toggled(self, event: ChoicePicker.Toggled) -> None:
        self._update_preview()

    def on_descendant_focus(self, event) -> None:
        self._update_help()

    def action_run(self) -> None:
        self._launch_script()

    def action_edit(self) -> None:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        cmd = shlex.split(editor) + [str(self.script_path)]
        with self.suspend():
            try:
                subprocess.run(cmd)
            except FileNotFoundError:
                print(f"argh: editor not found: {cmd[0]}")
                prev = signal.signal(signal.SIGINT, lambda *_: os._exit(0))
                try:
                    input("Press Enter to return to argh... ")
                except EOFError:
                    os._exit(0)
                finally:
                    signal.signal(signal.SIGINT, prev)

    def action_escape(self) -> None:
        row = self._focused_row()
        if row is not None and row.modified:
            row.reset()
            self._update_preview()
            return
        self.exit()

    def _focused_row(self) -> ArgRow | None:
        for row in self.rows:
            if row.value_widget.has_focus:
                return row
        return None

    def _refresh(self) -> None:
        self._update_help()
        self._update_preview()

    def _update_help(self) -> None:
        row = self._focused_row()
        if row is None:
            return
        spec = row.spec
        text = spec.help or ""
        if spec.choices:
            choices = ", ".join(str(c) for c in spec.choices)
            text = f"{text}\nchoices: {choices}" if text else f"choices: {choices}"
        self.query_one("#help", Static).update(text)

    def _update_preview(self) -> None:
        cmd = self._build_command()
        text = " ".join(shlex.quote(str(c)) for c in cmd)
        self.query_one("#preview", Static).update(f"$ {text}")

    def _build_command(self) -> list[str]:
        cmd: list[str] = [str(self.python_path), str(self.script_path)]
        for row in self.rows:
            spec = row.spec
            opt = spec.option_strings[0] if spec.option_strings else None
            widget = row.value_widget
            if spec.is_bool_flag:
                if widget.modified and opt:
                    cmd.append(opt)
                continue
            if isinstance(widget, ChoicePicker):
                if not widget.modified:
                    continue
                if spec.positional:
                    cmd.append(widget.value)
                else:
                    if opt:
                        cmd.append(opt)
                    cmd.append(widget.value)
                continue
            value = widget.value
            if value == "":
                continue
            if spec.is_list:
                if opt:
                    cmd.append(opt)
                cmd.extend(value.split())
            elif spec.positional:
                cmd.append(value)
            else:
                if opt:
                    cmd.append(opt)
                cmd.append(value)
        return cmd

    def _launch_script(self) -> None:
        cmd = self._build_command()
        with self.suspend():
            print()
            print(f"$ {' '.join(shlex.quote(str(c)) for c in cmd)}")
            print()
            try:
                result = subprocess.run(cmd)
                exit_code = result.returncode
            except KeyboardInterrupt:
                exit_code = 130
            print()
            print(f"[exit code {exit_code}]")
            # textual's asyncio loop installs its own SIGINT handler that doesn't
            # raise KeyboardInterrupt; install an immediate-exit handler so Ctrl+C
            # leaves promptly instead of needing a follow-up keypress.
            prev = signal.signal(signal.SIGINT, lambda *_: os._exit(0))
            try:
                input("Press Enter to return to argh, Ctrl+C to quit... ")
            except EOFError:
                os._exit(0)
            finally:
                signal.signal(signal.SIGINT, prev)
