from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Input, Label, TextArea


def _standard_edit_bindings() -> list[Binding]:
    return [
        Binding("ctrl+a,super+a", "select_all", "Select all", show=False, priority=True),
        Binding("ctrl+c,super+c", "copy", "Copy", show=False, priority=True),
        Binding("ctrl+x,super+x", "cut", "Cut", show=False, priority=True),
        Binding("ctrl+v,super+v", "paste", "Paste", show=False, priority=True),
    ]


class EditableTextArea(TextArea):
    """Text area with conventional clipboard and select-all shortcuts."""

    BINDINGS = [*TextArea.BINDINGS, *_standard_edit_bindings()]


class EditableInput(Input):
    """Single-line input with conventional clipboard and select-all shortcuts."""

    BINDINGS = [*Input.BINDINGS, *_standard_edit_bindings()]


class PagedTextScreen(ModalScreen[dict[str, str] | None]):
    """Shared keyboard navigation for modal forms composed of text pages."""

    FIELD_ORDER: ClassVar[list[tuple[str, str, str]]]
    SWITCHER_SELECTOR: ClassVar[str]
    STATUS_SELECTOR: ClassVar[str]

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("alt+right", "next_field", "Next Field", show=False, priority=True),
        Binding("alt+left", "previous_field", "Previous Field", show=False, priority=True),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_field_index = 0

    def on_mount(self) -> None:
        self.show_field(0)

    def show_field(self, index: int) -> None:
        self.current_field_index = index % len(self.FIELD_ORDER)
        page_id, field_id, label = self.FIELD_ORDER[self.current_field_index]
        self.query_one(self.SWITCHER_SELECTOR, ContentSwitcher).current = page_id
        self.query_one(self.STATUS_SELECTOR, Label).update(
            f"{label} ({self.current_field_index + 1}/{len(self.FIELD_ORDER)})"
        )
        self.query_one(f"#{field_id}", TextArea).focus()

    def action_next_field(self) -> None:
        self.show_field(self.current_field_index + 1)

    def action_previous_field(self) -> None:
        self.show_field(self.current_field_index - 1)
