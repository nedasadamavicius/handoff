from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, Input, Label, TextArea

from handoff.tui_forms import EditableInput, EditableTextArea, PagedTextScreen
from handoff.weekly import week_label


EntryKind = Literal["file", "folder"]


class HandoffScreen(PagedTextScreen):
    FIELD_ORDER = [
        ("page-summary", "handoff-summary", "Summary"),
        ("page-done", "handoff-done", "Completed"),
        ("page-open", "handoff-open", "Open issues"),
        ("page-next", "handoff-next", "Next session"),
    ]
    SWITCHER_SELECTOR = "#handoff-pages"
    STATUS_SELECTOR = "#handoff-page-status"

    CSS = """
    HandoffScreen {
        align: center middle;
    }

    #handoff-dialog {
        width: 88;
        height: 90%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #handoff-title {
        height: auto;
        text-style: bold;
        color: $accent;
        padding: 0;
    }

    #handoff-page-status {
        height: auto;
        color: $text-muted;
        padding: 0 0 1 0;
        border-bottom: solid $panel-darken-2;
    }

    .field-label {
        height: auto;
        padding: 1 0;
        text-style: bold;
        color: $text-muted;
    }

    #handoff-pages {
        height: 1fr;
        margin-top: 1;
    }

    .handoff-page {
        height: 1fr;
    }

    .handoff-field {
        height: 1fr;
        border: round $secondary;
    }

    #handoff-buttons {
        height: auto;
        align-horizontal: right;
    }

    #handoff-footer {
        height: auto;
        padding-top: 1;
    }

    #handoff-help {
        width: 1fr;
        color: $text-muted;
    }

    .handoff-button {
        width: 9;
    }
    """

    def __init__(
        self,
        workspace_name: str,
        summary: str,
        done: str,
        open_items: str,
        next_template: str,
        evidence: str = "",
    ) -> None:
        super().__init__()
        self.workspace_name = workspace_name
        self.summary = summary
        self.done = done
        self.open_items = open_items
        self.next_template = next_template
        self.evidence = evidence

    def compose(self) -> ComposeResult:
        with Vertical(id="handoff-dialog"):
            yield Label(f"Session Handoff - {self.workspace_name}", id="handoff-title")
            yield Label("", id="handoff-page-status")
            with ContentSwitcher(initial="page-summary", id="handoff-pages"):
                with Vertical(id="page-summary", classes="handoff-page"):
                    yield Label("Summary", classes="field-label")
                    yield EditableTextArea(
                        self.summary,
                        id="handoff-summary",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-done", classes="handoff-page"):
                    yield Label("Completed", classes="field-label")
                    yield EditableTextArea(
                        self.done,
                        id="handoff-done",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-open", classes="handoff-page"):
                    yield Label("Open issues", classes="field-label")
                    yield EditableTextArea(
                        self.open_items,
                        id="handoff-open",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-next", classes="handoff-page"):
                    yield Label("Next session", classes="field-label")
                    yield EditableTextArea(
                        self.next_template,
                        id="handoff-next",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                if self.evidence:
                    with Vertical(id="page-evidence", classes="handoff-page"):
                        yield Label("Evidence", classes="field-label")
                        yield EditableTextArea(
                            self.evidence,
                            id="handoff-evidence",
                            classes="handoff-field",
                            read_only=True,
                            soft_wrap=True,
                            show_line_numbers=False,
                        )
            with Horizontal(id="handoff-footer"):
                yield Label(
                    "Alt+</>        switch fields\n"
                    "Ctrl+A         select all\n"
                    "Ctrl+C/X/V     copy/cut/paste\n"
                    "Ctrl+S         save\n"
                    "Esc            cancel",
                    id="handoff-help",
                )
                with Horizontal(id="handoff-buttons"):
                    yield Button("Cancel", id="cancel", classes="handoff-button")
                    yield Button("Save", id="save", variant="primary", classes="handoff-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(
            {
                "summary": self.query_one("#handoff-summary", TextArea).text,
                "done": self.query_one("#handoff-done", TextArea).text,
                "open": self.query_one("#handoff-open", TextArea).text,
                "next": self.query_one("#handoff-next", TextArea).text,
                "evidence": self.evidence,
            }
        )

class NewEntryScreen(ModalScreen[str | None]):
    CSS = """
    NewEntryScreen {
        align: center middle;
    }

    #new-entry-dialog {
        width: 60;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #new-entry-title {
        height: auto;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #new-entry-input {
        margin-top: 1;
    }

    #new-entry-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    .new-entry-button {
        width: 9;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, directory: Path, entry_kind: EntryKind) -> None:
        super().__init__()
        self.directory = directory
        self.entry_kind = entry_kind

    def compose(self) -> ComposeResult:
        with Vertical(id="new-entry-dialog"):
            yield Label(f"New {self.entry_kind} in {self.directory.name}/", id="new-entry-title")
            placeholder = "folder-name" if self.entry_kind == "folder" else "filename.md"
            yield EditableInput(placeholder=placeholder, id="new-entry-input")
            with Horizontal(id="new-entry-buttons"):
                yield Button("Cancel", id="cancel", classes="new-entry-button")
                yield Button("Create", id="create", variant="primary", classes="new-entry-button")

    def on_mount(self) -> None:
        self.query_one("#new-entry-input", Input).focus()

    def on_input_submitted(self) -> None:
        self.action_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self.action_create()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_create(self) -> None:
        name = self.query_one("#new-entry-input", Input).value.strip()
        self.dismiss(name if name else None)


class WeeklyReviewScreen(PagedTextScreen):
    FIELD_ORDER = [
        ("page-summary", "weekly-summary", "Summary"),
        ("page-highlights", "weekly-highlights", "Highlights"),
        ("page-carry", "weekly-carry", "Carry-forwards"),
    ]
    SWITCHER_SELECTOR = "#weekly-pages"
    STATUS_SELECTOR = "#weekly-page-status"

    CSS = """
    WeeklyReviewScreen {
        align: center middle;
    }

    #weekly-dialog {
        width: 88;
        height: 90%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #weekly-title {
        height: auto;
        text-style: bold;
        color: $accent;
        padding: 0;
    }

    #weekly-page-status {
        height: auto;
        color: $text-muted;
        padding: 0 0 1 0;
        border-bottom: solid $panel-darken-2;
    }

    #weekly-pages {
        height: 1fr;
        margin-top: 1;
    }

    .weekly-page {
        height: 1fr;
    }

    .weekly-field-label {
        height: auto;
        padding: 1 0;
        text-style: bold;
        color: $text-muted;
    }

    .weekly-field {
        height: 1fr;
        border: round $secondary;
    }

    #weekly-buttons {
        height: auto;
        align-horizontal: right;
    }

    #weekly-footer {
        height: auto;
        padding-top: 1;
    }

    #weekly-help {
        width: 1fr;
        color: $text-muted;
    }

    .weekly-button {
        width: 9;
    }
    """

    def __init__(self, year: int, week: int, summary: str, highlights: str, carry_forwards: str) -> None:
        super().__init__()
        self.year = year
        self.week = week
        self.summary = summary
        self.highlights = highlights
        self.carry_forwards = carry_forwards

    def compose(self) -> ComposeResult:
        label = week_label(self.year, self.week)
        with Vertical(id="weekly-dialog"):
            yield Label(f"Weekly Review — {label}", id="weekly-title")
            yield Label("", id="weekly-page-status")
            with ContentSwitcher(initial="page-summary", id="weekly-pages"):
                with Vertical(id="page-summary", classes="weekly-page"):
                    yield Label("Summary", classes="weekly-field-label")
                    yield EditableTextArea(
                        self.summary,
                        id="weekly-summary",
                        classes="weekly-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-highlights", classes="weekly-page"):
                    yield Label("Highlights  (what shipped this week)", classes="weekly-field-label")
                    yield EditableTextArea(
                        self.highlights,
                        id="weekly-highlights",
                        classes="weekly-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-carry", classes="weekly-page"):
                    yield Label("Carry-forwards  (open items into next week)", classes="weekly-field-label")
                    yield EditableTextArea(
                        self.carry_forwards,
                        id="weekly-carry",
                        classes="weekly-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
            with Horizontal(id="weekly-footer"):
                yield Label(
                    "Alt+Left/Right switch fields\n"
                    "Ctrl+A select all  Ctrl+C/X/V copy/cut/paste\n"
                    "Ctrl+S save  Esc cancel",
                    id="weekly-help",
                )
                with Horizontal(id="weekly-buttons"):
                    yield Button("Skip", id="cancel", classes="weekly-button")
                    yield Button("Save", id="save", variant="primary", classes="weekly-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss({
            "summary": self.query_one("#weekly-summary", TextArea).text,
            "highlights": self.query_one("#weekly-highlights", TextArea).text,
            "carry_forwards": self.query_one("#weekly-carry", TextArea).text,
        })

