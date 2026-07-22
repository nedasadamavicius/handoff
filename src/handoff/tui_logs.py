from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Label, ListItem, ListView, MarkdownViewer

from handoff.documents import strip_yaml_frontmatter
from handoff.workspace import Workspace, preview_file


class LogPreview(MarkdownViewer):
    can_focus = True

    BINDINGS = [
        Binding("left", "back_to_list", "List", show=False, priority=True),
        Binding("right", "stay_in_preview", "Preview", show=False, priority=True),
    ]

    def action_back_to_list(self) -> None:
        screen = self.screen
        if isinstance(screen, LogBrowserScreen):
            screen.action_back_to_list()

    def action_stay_in_preview(self) -> None:
        pass


class LogBrowserScreen(ModalScreen[Path | None]):
    TABS = ["sessions", "days", "weeks"]

    CSS = """
    LogBrowserScreen {
        align: center middle;
    }

    #log-browser-dialog {
        width: 95%;
        height: 95%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #log-browser-title {
        height: auto;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #log-body {
        height: 1fr;
        margin-top: 1;
    }

    #log-list-pane {
        width: 30;
        border-right: solid $panel;
        padding-right: 1;
    }

    #log-list-pane.active-pane {
        border-right: solid $accent;
    }

    #log-tab-status {
        height: auto;
        color: $text-muted;
        padding: 0 0 1 0;
    }

    #log-tabs {
        height: 1fr;
    }

    #log-preview {
        height: 1fr;
        overflow-x: hidden;
    }

    #log-preview-pane {
        width: 1fr;
        height: 1fr;
        border-left: thick $surface;
        padding-left: 1;
    }

    #log-preview-pane.active-pane {
        border-left: thick $accent;
    }

    #log-preview-status {
        height: auto;
        color: $text-muted;
        padding: 0 1;
    }

    #log-preview-pane.active-pane #log-preview-status {
        background: $accent;
        color: $surface;
        text-style: bold;
    }

    #log-footer {
        height: auto;
        padding-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "handle_escape", "Close", show=False),
        Binding("ctrl+right", "next_tab", "Next Tab", show=False, priority=True),
        Binding("ctrl+left", "previous_tab", "Prev Tab", show=False, priority=True),
        Binding("up", "nav_up", "Up", show=False, priority=True),
        Binding("down", "nav_down", "Down", show=False, priority=True),
        Binding("left", "back_to_list", "List", show=False, priority=True),
        Binding("right", "focus_preview", "Preview", show=False, priority=True),
        Binding("enter", "open_selected", "Open", show=False, priority=True),
        Binding("e", "edit_selected", "Edit", show=False),
    ]

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self.workspace = workspace
        self.tab_index = 0
        self._focus_pane = "list"
        self._preview_path: Path | None = None
        self._files: dict[str, list[Path]] = {t: [] for t in self.TABS}

    def compose(self) -> ComposeResult:
        with Vertical(id="log-browser-dialog"):
            yield Label("Log Browser", id="log-browser-title")
            with Horizontal(id="log-body"):
                with Vertical(id="log-list-pane", classes="active-pane"):
                    yield Label("", id="log-tab-status")
                    with ContentSwitcher(id="log-tabs", initial="tab-sessions"):
                        yield ListView(id="tab-sessions")
                        yield ListView(id="tab-days")
                        yield ListView(id="tab-weeks")
                with Vertical(id="log-preview-pane"):
                    yield Label("Preview", id="log-preview-status")
                    yield LogPreview(
                        "Select an entry and press Enter to scroll.",
                        show_table_of_contents=False,
                        id="log-preview",
                    )
            yield Label(
                "↑↓ navigate · Enter load · → preview · ← list · "
                "Ctrl+←/→ switch tabs · e edit · Esc close",
                id="log-footer",
            )

    def on_mount(self) -> None:
        self._populate_all()
        self._switch_tab(0)

    def _format_stem(self, stem: str) -> str:
        parts = stem.split("-")
        if len(parts) == 4 and len(parts[3]) == 6 and parts[3].isdigit():
            return f"{'-'.join(parts[:3])}  {parts[3][:2]}:{parts[3][2:4]}"
        return stem

    def _populate_all(self) -> None:
        dirs = {
            "sessions": self.workspace.sessions_dir,
            "days": self.workspace.days_dir,
            "weeks": self.workspace.weeks_dir,
        }
        for tab, directory in dirs.items():
            lv = self.query_one(f"#tab-{tab}", ListView)
            files = sorted(directory.glob("*.md"), reverse=True) if directory.exists() else []
            self._files[tab] = files
            if not files:
                lv.append(ListItem(Label("No entries yet.")))
            else:
                for path in files:
                    lv.append(ListItem(Label(self._format_stem(path.stem))))

    def _switch_tab(self, index: int) -> None:
        self.tab_index = index % len(self.TABS)
        tab = self.TABS[self.tab_index]
        self.query_one("#log-tabs", ContentSwitcher).current = f"tab-{tab}"
        self._focus_pane = "list"
        self._update_pane_styles()
        list_view = self.query_one(f"#tab-{tab}", ListView)
        if self._files[tab] and list_view.index is None:
            list_view.index = 0
        list_view.focus()

    def _update_pane_styles(self) -> None:
        in_preview = self._focus_pane == "preview"
        self.query_one("#log-list-pane", Vertical).set_class(not in_preview, "active-pane")
        self.query_one("#log-preview-pane", Vertical).set_class(in_preview, "active-pane")
        tab = self.TABS[self.tab_index]
        self.query_one("#log-tab-status", Label).update(
            f"{tab.capitalize()}  ({self.tab_index + 1}/{len(self.TABS)})"
        )
        self.query_one("#log-preview-status", Label).update("Preview")

    async def _load_preview(self, path: Path) -> None:
        text = strip_yaml_frontmatter(preview_file(path))
        preview = self.query_one("#log-preview", MarkdownViewer)
        await preview.document.update(text)
        preview.scroll_home(animate=False, immediate=True, force=True)

    def action_nav_up(self) -> None:
        if self._focus_pane == "preview":
            self.query_one("#log-preview", MarkdownViewer).scroll_up()
        else:
            tab = self.TABS[self.tab_index]
            self.query_one(f"#tab-{tab}", ListView).action_cursor_up()

    def action_nav_down(self) -> None:
        if self._focus_pane == "preview":
            self.query_one("#log-preview", MarkdownViewer).scroll_down()
        else:
            tab = self.TABS[self.tab_index]
            self.query_one(f"#tab-{tab}", ListView).action_cursor_down()

    def _open_selected(self, list_view: ListView) -> None:
        tab = self.TABS[self.tab_index]
        index = list_view.index
        if index is None or index >= len(self._files[tab]):
            return
        path = self._files[tab][index]
        self._preview_path = path
        self.run_worker(self._load_preview(path), exclusive=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._focus_pane == "list":
            self._open_selected(event.list_view)

    def action_open_selected(self) -> None:
        if self._focus_pane != "list":
            return
        tab = self.TABS[self.tab_index]
        self._open_selected(self.query_one(f"#tab-{tab}", ListView))

    def action_focus_preview(self) -> None:
        if self._focus_pane != "list" or self._preview_path is None:
            return
        self._focus_pane = "preview"
        self._update_pane_styles()
        self.query_one("#log-preview", MarkdownViewer).focus()

    def action_back_to_list(self) -> None:
        if self._focus_pane != "preview":
            return
        self._focus_pane = "list"
        tab = self.TABS[self.tab_index]
        self.query_one("#log-preview", MarkdownViewer).scroll_home(
            animate=False,
            immediate=True,
            force=True,
            y_axis=False,
        )
        self._update_pane_styles()
        self.query_one(f"#tab-{tab}", ListView).focus()

    def action_handle_escape(self) -> None:
        self.dismiss(None)

    def action_next_tab(self) -> None:
        self._switch_tab(self.tab_index + 1)

    def action_previous_tab(self) -> None:
        self._switch_tab(self.tab_index - 1)

    def action_edit_selected(self) -> None:
        tab = self.TABS[self.tab_index]
        lv = self.query_one(f"#tab-{tab}", ListView)
        index = lv.index
        if index is None:
            return
        files = self._files[tab]
        if index >= len(files):
            return
        self.dismiss(files[index])


