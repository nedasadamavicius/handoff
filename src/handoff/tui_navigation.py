from __future__ import annotations

from textual import events
from textual.actions import SkipAction
from textual.containers import VerticalScroll
from textual.errors import NoWidget
from textual.widgets import DirectoryTree, MarkdownViewer, TextArea

OVERVIEW_AREAS = ("last", "next")
SCROLL_METHODS = {
    "up": "scroll_up",
    "down": "scroll_down",
    "page_up": "scroll_page_up",
    "page_down": "scroll_page_down",
    "home": "scroll_home",
    "end": "scroll_end",
}
MARKDOWN_VIEWER_SCROLL_METHODS = {
    "up": "action_scroll_up",
    "down": "action_scroll_down",
    "page_up": "action_page_up",
    "page_down": "action_page_down",
    "home": "action_scroll_home",
    "end": "action_scroll_end",
}
NAVIGATION_KEY_ACTIONS = {
    "up": "action_move_up",
    "down": "action_move_down",
    "pageup": "action_page_up",
    "pagedown": "action_page_down",
    "home": "action_scroll_home",
    "end": "action_scroll_end",
    "enter": "action_select_focused",
}


class PaneNavigationMixin:
    """Pane focus, mouse routing and keyboard navigation for the workspace shell."""

    def action_move_up(self) -> None:
        self._move_selection("up")

    def action_move_down(self) -> None:
        self._move_selection("down")

    def _move_selection(self, direction: str) -> None:
        if isinstance(self.focused, TextArea) or self._scroll_focused_pane(direction):
            return
        if isinstance(self.focused, DirectoryTree):
            cursor_actions = {"up": self.focused.action_cursor_up, "down": self.focused.action_cursor_down}
            cursor_actions[direction]()
            return
        self.query_one("#file-tree", DirectoryTree).focus()

    def _scroll_focused_pane(self, direction: str) -> bool:
        """Scroll the preview or overview pane that has focus; False when neither does."""
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview(direction)
            return True
        if self.focus_area in OVERVIEW_AREAS:
            self._scroll_overview_panel(self.focus_area, direction)
            return True
        return False

    def action_focus_tree(self) -> None:
        self.focus_area = "files"
        self.query_one("#file-tree", DirectoryTree).focus()
        self.update_focus_styles()

    def action_focus_preview(self) -> None:
        if self.preview_mode:
            self.focus_area = "preview"
            self.update_focus_styles()

    def action_focus_next_overview_panel(self) -> None:
        if self.focus_area == "last":
            self.focus_area = "next"
            self.update_focus_styles()

    def pane_for_widget(self, widget) -> str | None:
        """Map a clicked widget to the focus area of the pane containing it."""
        node = widget
        while node is not None:
            node_id = getattr(node, "id", None)
            if node_id == "browser":
                return "files"
            if node_id in ("preview", "text-preview"):
                return "preview" if self.preview_mode else None
            if node_id == "last-container":
                return "last"
            if node_id == "next-container":
                return "next"
            node = node.parent
        return None

    async def on_event(self, event: events.Event) -> None:
        # Pick the pane as soon as the raw click arrives, instead of waiting for the
        # forwarded MouseDown to bubble back up through every nested widget.
        if isinstance(event, events.MouseDown) and not event.is_forwarded:
            self.focus_pane_at(event.screen_x, event.screen_y)
        await super().on_event(event)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # Fallback for clicks injected past on_event (e.g. Textual's test pilot); a
        # no-op when on_event already handled the click.
        self.focus_pane_at(event.screen_x, event.screen_y)

    def focus_pane_at(self, x: int, y: int) -> None:
        try:
            widget, _ = self.screen.get_widget_at(x, y)
        except NoWidget:
            return
        area = self.pane_for_widget(widget)
        if area is None:
            return
        tree = self.query_one("#file-tree", DirectoryTree)
        if area == self.focus_area and self.focused is tree:
            return
        self.focus_area = area
        # Navigation keys are routed through the tree, so it keeps keyboard focus.
        tree.focus(scroll_visible=False)
        self.update_focus_styles()

    def update_focus_styles(self) -> None:
        # Set the focus border inline rather than toggling a CSS class: a class change
        # restyles every descendant (each Markdown block), which made focus moves lag.
        # Clearing the inline border falls back to the pane's stylesheet border.
        focused = {
            "#browser": self.focus_area == "files",
            "#preview": self.focus_area == "preview" and self.active_preview == "markdown",
            "#text-preview": self.focus_area == "preview" and self.active_preview == "text",
            "#last-container": self.focus_area == "last",
            "#next-container": self.focus_area == "next",
        }
        accent = self.get_css_variables()["accent"]
        for selector, is_focused in focused.items():
            pane = self.query_one(selector)
            pane.styles.border = ("heavy", accent) if is_focused else None

    def handle_navigation_key(self, key: str) -> None:
        if isinstance(self.focused, TextArea):
            return
        if key == "left":
            self._focus_pane_left()
        elif key == "right":
            self._focus_pane_right()
        elif key in NAVIGATION_KEY_ACTIONS:
            getattr(self, NAVIGATION_KEY_ACTIONS[key])()

    def _focus_pane_left(self) -> None:
        if self.focus_area == "next":
            self.focus_area = "last"
            self.update_focus_styles()
        else:
            self.action_focus_tree()

    def _focus_pane_right(self) -> None:
        if self.focus_area == "last":
            self.action_focus_next_overview_panel()
        elif self.focus_area == "files" and not self.preview_mode:
            self.focus_area = "last"
            self.update_focus_styles()
        else:
            self.action_focus_preview()

    def _scroll_overview_panel(self, area: str, direction: str) -> None:
        scroller = self.query_one(f"#{area}-scroll", VerticalScroll)
        getattr(scroller, SCROLL_METHODS[direction])()

    def action_page_up(self) -> None:
        self._scroll_focused_pane("page_up")

    def action_page_down(self) -> None:
        self._scroll_focused_pane("page_down")

    def action_scroll_home(self) -> None:
        self._scroll_focused_pane("home")

    def action_scroll_end(self) -> None:
        self._scroll_focused_pane("end")

    def scroll_preview(self, direction: str) -> None:
        preview = self.current_preview_widget()
        method_names = MARKDOWN_VIEWER_SCROLL_METHODS if isinstance(preview, MarkdownViewer) else SCROLL_METHODS
        try:
            getattr(preview, method_names[direction])()
        except SkipAction:
            pass

    def current_preview_widget(self):
        if self.active_preview == "text":
            return self.query_one("#text-preview", TextArea)
        return self.query_one("#preview", MarkdownViewer)

    def action_select_focused(self) -> None:
        if self.focus_area != "files":
            return
        focused = self.focused
        if isinstance(focused, DirectoryTree):
            focused.action_select_cursor()
