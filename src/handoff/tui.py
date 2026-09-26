from __future__ import annotations

import asyncio
import os
from pathlib import Path

from textual import events
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.errors import NoWidget
from textual.widgets import Button, ContentSwitcher, DataTable, DirectoryTree, Footer, Label, Markdown, MarkdownViewer, TextArea

from handoff.config import AppConfig
from handoff.agent_runs import RunLedger
from handoff.tui_agents import QuitAgentScreen
from handoff.external_sessions import SessionManager
from handoff.tui_sessions import SessionManagerWidget
from handoff.documents import (
    MARKDOWN_SUFFIXES,
    deduplicate_next_lines,
    is_markdown_file,
    merge_next_text,
    normalize_list_text,
    render_last_markdown,
    render_next_markdown,
    strip_first_heading,
    strip_first_subheading,
    strip_handoff_frontmatter,
    strip_next_heading,
    strip_yaml_frontmatter,
)
from handoff.git import changed_files_from_status, git_status_short
from handoff.launcher import (
    LaunchError,
    editor_command,
    is_terminal_editor,
    next_audit_command,
    run_command,
    spawn_detached,
)
from handoff.handoff import draft_has_content, parse_draft_or_files, parse_last_sections
from handoff.session import now_local
from handoff.theme import ensure_themes_dir, register_all_themes
from handoff.tui_forms import EditableInput, EditableTextArea
from handoff.tui_logs import LogBrowserScreen, LogPreview
from handoff.tui_screens import EntryKind, HandoffScreen, KnowledgeScreen, NewEntryScreen, WeeklyReviewScreen, WorkspaceModeScreen
from handoff.weekly import (
    append_week_to_worklog,
    auto_generate_draft,
    finalize_week_draft,
    find_pending_weeks,
    read_week_draft,
    week_label,
)
from handoff.workflows import save_workspace_handoff
from handoff.workspace import (
    Workspace,
    ensure_tool_file,
    ensure_workspace_files,
    infer_workspace_type,
    preview_file,
    set_workspace_mode,
    workspace_type,
    workspace_mode,
)


HIDDEN_TREE_NAMES = {
    ".git",
    ".handoff",
    ".claude",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
HIDDEN_TREE_SUFFIXES = {".pyc", ".pyo"}
WATCH_INTERVAL = 1.0


def is_tree_visible(name: str) -> bool:
    return name not in HIDDEN_TREE_NAMES and Path(name).suffix not in HIDDEN_TREE_SUFFIXES


def directory_signature(directories: list[Path]) -> tuple:
    """Names and kinds of the visible entries in each directory, for change detection."""
    signature = []
    for directory in directories:
        try:
            with os.scandir(directory) as entries:
                listing = tuple(sorted((entry.name, entry.is_dir()) for entry in entries if is_tree_visible(entry.name)))
        except OSError:
            listing = None
        signature.append((str(directory), listing))
    return tuple(signature)


def file_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class WorkspaceDirectoryTree(DirectoryTree):
    def filter_paths(self, paths):
        return [path for path in paths if is_tree_visible(path.name)]

    def expanded_paths(self) -> list[Path]:
        paths = []
        pending = [self.root]
        while pending:
            node = pending.pop()
            if node.data is not None and (node is self.root or node.is_expanded):
                paths.append(Path(node.data.path))
                pending.extend(child for child in node.children if child.allow_expand)
        return paths

    def on_key(self, event) -> None:
        if event.key in {"left", "right", "up", "down", "pageup", "pagedown", "home", "end", "enter"}:
            event.stop()
            self.app.handle_navigation_key(event.key)


class WorkspaceShell(App):
    TITLE = "handoff"

    CSS = """
    * {
        scrollbar-size-vertical: 1;
    }

    #root {
        height: 100%;
    }

    #browser {
        width: 40;
        border: round $primary 35%;
    }


    #right-pane {
        width: 1fr;
    }

    #right-switcher {
        height: 1fr;
    }

    #overview-view {
        height: 1fr;
    }

    #preview-view {
        height: 1fr;
    }

    #agents-view {
        height: 1fr;
    }

    #last-container {
        width: 1fr;
        height: 1fr;
        border: round $success;
    }


    #next-container {
        width: 1fr;
        height: 1fr;
        border: round $warning 55%;
    }


    #last-header {
        height: auto;
        padding: 0 1;
        text-style: bold;
        color: $success;
        background: $success 15%;
        border-bottom: solid $success;
    }

    #next-header {
        height: auto;
        padding: 0 1;
        background: $warning 12%;
        border-bottom: solid $warning;
        align: left middle;
    }

    #next-title {
        width: 1fr;
        height: auto;
        text-style: bold;
        color: $warning;
        content-align: left middle;
    }

    #next-audit {
        width: auto;
        min-width: 9;
        height: 1;
        margin: 0 0 0 1;
        padding: 0 1;
        border: none;
        background: $warning 25%;
        color: $text;
        text-style: none;
    }

    #next-audit:hover {
        background: $warning 45%;
    }

    #last-scroll {
        height: 1fr;
    }

    #next-scroll {
        height: 1fr;
    }

    #last-panel {
        width: 1fr;
        height: auto;
        padding: 1 2;
    }

    #next-panel {
        width: 1fr;
        height: auto;
        padding: 1 2;
    }

    #file-tree {
        height: 1fr;
        background: $background;
    }

    #file-tree:focus {
        background-tint: $foreground 0%;
    }

    #preview {
        height: 100%;
        border: round $secondary;
        padding: 1;
        background: $background;
    }

    #text-preview {
        height: 100%;
        border: round $secondary;
        background: $background;
    }


    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("e", "edit", "Edit"),
        Binding("h", "handoff", "Handoff"),
        Binding("w", "edit_workspace_context", "Edit Context"),
        Binding("l", "edit_last", "Edit Last"),
        Binding("n", "edit_next", "Edit Next"),
        Binding("N", "audit_next", "Audit Next"),
        Binding("t", "tool", "Tool"),
        Binding("ctrl+t", "detach_tool", "Detach Tool", show=False, priority=True),
        Binding("ctrl+k", "kill_tool", "Kill Tool", show=False, priority=True),
        Binding("W", "weekly_review", "Week Review"),
        Binding("s", "log_browser", "Logs"),
        Binding("g", "knowledge", "Knowledge"),
        Binding("ctrl+h", "handoff", "Handoff", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+s", "handoff", "Handoff", show=False, priority=True),
        Binding("1", "launch_tool(0)", "Tool 1", show=False),
        Binding("2", "launch_tool(1)", "Tool 2", show=False),
        Binding("3", "launch_tool(2)", "Tool 3", show=False),
        Binding("4", "launch_tool(3)", "Tool 4", show=False),
        Binding("5", "launch_tool(4)", "Tool 5", show=False),
        Binding("left", "focus_tree", "Files", show=False),
        Binding("right", "focus_preview", "Preview", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
        Binding("enter", "select_focused", "Select", show=False),
        Binding("c", "new_file", "New File"),
        Binding("d", "new_folder", "New Folder"),
    ]

    def __init__(self, config: AppConfig, workspace: Workspace) -> None:
        super().__init__()
        self.config = config
        self.workspace = workspace
        self.active_file: Path | None = None
        self.started_at = now_local()
        self.files_opened: list[str] = []
        self.tools_launched: list[str] = []
        self.tool_picker_open = False
        self.preview_mode = False
        self.focus_area = "files"
        self.active_preview = "markdown"
        self.pending_weeks: list[tuple[int, int]] = []
        self.run_ledger = RunLedger(workspace)
        self.session_manager = SessionManager(self.workspace.path)
        self.session_widget: SessionManagerWidget | None = None
        self.quit_after_handoff = False
        self._next_audit_running = False
        self._watch_busy = False
        self._watch_state: tuple | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="root"):
            with Vertical(id="browser"):
                yield WorkspaceDirectoryTree(str(self.workspace.path), id="file-tree")
            with Vertical(id="right-pane"):
                with ContentSwitcher(id="right-switcher", initial="overview-view"):
                    with Horizontal(id="overview-view"):
                        with Vertical(id="last-container"):
                            yield Label("Last Session", id="last-header")
                            with VerticalScroll(id="last-scroll"):
                                yield Markdown("", id="last-panel")
                        with Vertical(id="next-container"):
                            with Horizontal(id="next-header"):
                                yield Label("What's Next", id="next-title")
                                yield Button("Audit", id="next-audit")
                            with VerticalScroll(id="next-scroll"):
                                yield Markdown("", id="next-panel")
                    with Vertical(id="preview-view"):
                        yield MarkdownViewer("", show_table_of_contents=False, id="preview")
                    with Vertical(id="text-preview-view"):
                        yield TextArea(
                            "",
                            read_only=True,
                            show_cursor=False,
                            show_line_numbers=False,
                            id="text-preview",
                        )
                    with Vertical(id="agents-view"):
                        self.session_widget = SessionManagerWidget(self.session_manager, self.config, self.workspace.path, ledger=self.run_ledger)
                        yield self.session_widget
        yield Footer()

    def on_mount(self) -> None:
        ensure_themes_dir(self.config.themes_dir)
        register_all_themes(self, self.config)
        self.query_one("#file-tree", DirectoryTree).focus()
        # Clicks pick the pane via on_mouse_down; letting these widgets grab focus
        # first would bounce focus away from the tree and rebuild the footer twice.
        for widget in self.query("#last-scroll, #next-scroll, #next-audit, #preview, #text-preview"):
            widget.focus_on_click = lambda: False
        self.theme_changed_signal.subscribe(self, lambda _theme: self.update_focus_styles())
        had_workspace_file = self.workspace.workspace_file.exists()
        kind = workspace_type(self.workspace) or infer_workspace_type(self.workspace)
        ensure_workspace_files(self.workspace, workspace_kind=kind, workspace_mode=None if had_workspace_file else "coding")
        mode = workspace_mode(self.workspace)
        self.sub_title = mode or kind
        self.show_workspace_overview()
        self.run_worker(asyncio.to_thread(self._rename_handoff_window), exclusive=False)
        self._check_pending_weeks()
        self.set_interval(WATCH_INTERVAL, self._watch_workspace)
        if mode is None and had_workspace_file:
            self.push_screen(WorkspaceModeScreen(), self._save_workspace_mode)

    def _rename_handoff_window(self) -> None:
        try:
            self.session_manager.rename_handoff_window()
        except Exception:
            pass

    def _save_workspace_mode(self, mode: str | None) -> None:
        if mode is None:
            self.notify("Choose Study or Coding to continue.", severity="warning")
            self.push_screen(WorkspaceModeScreen(), self._save_workspace_mode)
            return
        set_workspace_mode(self.workspace, mode)
        self.sub_title = mode
        self.notify("Study tools enabled." if mode == "study" else "Coding workspace ready.")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        nav_actions = {
            "move_up",
            "move_down",
            "focus_tree",
            "focus_preview",
            "page_up",
            "page_down",
            "scroll_home",
            "scroll_end",
            "select_focused",
        }
        if isinstance(self.focused, DataTable) and action in nav_actions:
            return False
        if action in nav_actions and len(self.screen_stack) > 1:
            return False
        if action == "handoff" and len(self.screen_stack) > 1:
            return False
        if isinstance(self.focused, TextArea) and action in nav_actions:
            return False
        return True

    async def _watch_workspace(self) -> None:
        """Poll the workspace and live-update the tree, overview, and open preview."""
        if self._watch_busy:
            return
        self._watch_busy = True
        try:
            tree = self.query_one("#file-tree", WorkspaceDirectoryTree)
            directories = tree.expanded_paths()
            active_file = self.active_file if self.preview_mode else None
            workspace = self.workspace
            state = await asyncio.to_thread(
                lambda: (
                    directory_signature(directories),
                    (file_signature(workspace.last_file), file_signature(workspace.next_file)),
                    (active_file, file_signature(active_file)),
                )
            )
            previous, self._watch_state = self._watch_state, state
            if previous is None:
                return
            if state[0] != previous[0]:
                await tree.reload()
            if state[1] != previous[1]:
                self.render_overview_panels()
            if state[2] != previous[2] and state[2][0] == previous[2][0] and active_file is not None:
                self.reload_active_preview()
        except Exception:
            pass
        finally:
            self._watch_busy = False

    def reload_active_preview(self) -> None:
        if self.active_file is None or not self.active_file.exists():
            return
        text = preview_file(self.active_file)
        if self.active_preview == "markdown":
            preview = self.query_one("#preview", MarkdownViewer)
            scroll_y = preview.scroll_y
            self.run_worker(preview.document.update(text), exclusive=True)
            self.call_after_refresh(preview.scroll_to, y=scroll_y, animate=False)
        else:
            preview = self.query_one("#text-preview", TextArea)
            scroll_y = preview.scroll_y
            preview.load_text(text)
            self.call_after_refresh(preview.scroll_to, y=scroll_y, animate=False)

    def render_overview_panels(self) -> None:
        workspace = self.workspace
        latest = workspace.last_handoff()
        next_text = (
            preview_file(workspace.next_file)
            if workspace.next_file.exists()
            else "No next actions yet.\n\nPress **n** to add some."
        )
        latest_text = (
            latest.body
            if latest
            else "No session recorded yet.\n\nPress **h** after working to save your first handoff."
        )
        last_text = strip_first_subheading(strip_first_heading(latest_text))
        self.query_one("#last-panel", Markdown).update(last_text)
        self.query_one("#next-panel", Markdown).update(strip_first_heading(next_text))

    def show_workspace_overview(self) -> None:
        self.query_one("#right-switcher", ContentSwitcher).current = "overview-view"
        self.render_overview_panels()
        self.tool_picker_open = False
        self.preview_mode = False
        self.focus_area = "files"
        self.query_one("#file-tree", DirectoryTree).focus()
        self.update_focus_styles()

    def show_single_panel(self, content: str) -> None:
        self.show_markdown_preview(content)

    def show_markdown_preview(self, content: str) -> None:
        self.query_one("#right-switcher", ContentSwitcher).current = "preview-view"
        preview = self.query_one("#preview", MarkdownViewer)
        self.run_worker(preview.document.update(content), exclusive=True)
        preview.scroll_home(animate=False)
        self.preview_mode = True
        self.active_preview = "markdown"
        self.focus_area = "files"
        self.query_one("#file-tree", DirectoryTree).focus()
        self.update_focus_styles()

    def show_text_preview(self, content: str) -> None:
        self.query_one("#right-switcher", ContentSwitcher).current = "text-preview-view"
        preview = self.query_one("#text-preview", TextArea)
        preview.load_text(content)
        preview.scroll_home(animate=False)
        self.preview_mode = True
        self.active_preview = "text"
        self.focus_area = "files"
        self.query_one("#file-tree", DirectoryTree).focus()
        self.update_focus_styles()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.active_file = Path(event.path)
        text = preview_file(self.active_file)
        relative = str(self.active_file.relative_to(self.workspace.path))
        if relative not in self.files_opened:
            self.files_opened.append(relative)
        if is_markdown_file(self.active_file):
            self.show_markdown_preview(text)
        else:
            self.show_text_preview(text)
        self.tool_picker_open = False

    def action_refresh(self) -> None:
        tree = self.query_one("#file-tree", DirectoryTree)
        tree.reload()
        self.show_workspace_overview()

    def _get_cursor_directory(self) -> Path:
        tree = self.query_one("#file-tree", WorkspaceDirectoryTree)
        node = tree.cursor_node
        if node is not None and node.data is not None:
            try:
                node_path = Path(node.data.path)
                return node_path if node_path.is_dir() else node_path.parent
            except (AttributeError, TypeError):
                pass
        return self.workspace.path

    def action_new_file(self) -> None:
        self._show_new_entry_dialog("file")

    def action_new_folder(self) -> None:
        self._show_new_entry_dialog("folder")

    def _show_new_entry_dialog(self, entry_kind: EntryKind) -> None:
        if self.focus_area != "files":
            return
        target_dir = self._get_cursor_directory()

        def on_result(name: str | None) -> None:
            if not name:
                return
            if name in {".", ".."} or Path(name).name != name:
                self.notify("Enter a name without path separators.", severity="warning")
                return
            new_path = target_dir / name
            if new_path.exists():
                self.notify(f"{name} already exists.", severity="warning")
                return
            try:
                if entry_kind == "folder":
                    new_path.mkdir()
                else:
                    new_path.touch()
            except OSError as exc:
                self.notify(str(exc), severity="error")
                return
            if entry_kind == "file":
                self.active_file = new_path
            self.action_refresh()

        self.push_screen(NewEntryScreen(target_dir, entry_kind), on_result)

    def action_edit(self) -> None:
        if self.active_file is None:
            self.notify("Select a file first.", severity="warning")
            return
        self.edit_path(self.active_file)

    def edit_path(self, path: Path) -> None:
        command = editor_command(self.config, path)
        try:
            if is_terminal_editor(command):
                with self.suspend():
                    run_command(command, cwd=self.workspace.path)
            else:
                spawn_detached(command, cwd=self.workspace.path)
        except LaunchError as exc:
            self.notify(str(exc), severity="error")
            return
        self.refresh_after_edit()

    def refresh_after_edit(self) -> None:
        """Reload the tree but keep whatever view was open before the editor ran."""
        self.query_one("#file-tree", DirectoryTree).reload()
        if self.preview_mode and self.active_file is not None and self.active_file.exists():
            self.reload_active_preview()
        elif self.preview_mode:
            self.show_workspace_overview()
        else:
            self.render_overview_panels()

    def action_edit_workspace_context(self) -> None:
        self.edit_path(self.workspace.workspace_file)

    def action_edit_last(self) -> None:
        strip_handoff_frontmatter(self.workspace.last_file)
        self.edit_path(self.workspace.last_file)

    def action_edit_next(self) -> None:
        self.edit_path(self.workspace.next_file)

    def action_audit_next(self) -> None:
        """Run a headless Sonnet job that cleans up NEXT.md from git history."""
        if not self.workspace.next_file.exists():
            self.notify("No Next file to audit yet.", severity="warning")
            return
        if self._next_audit_running:
            self.notify("A Next audit is already running.", severity="warning")
            return
        try:
            command = next_audit_command(self.config)
        except KeyError as exc:
            self.notify(str(exc), severity="error")
            return
        self._next_audit_running = True
        self.notify("Auditing Next with Sonnet...", timeout=6)
        self.run_worker(self._run_next_audit(command), exclusive=False)

    async def _run_next_audit(self, command: list[str]) -> None:
        backup = self.workspace.meta / "NEXT.bak.md"
        try:
            backup.write_text(self.workspace.next_file.read_text(encoding="utf-8"), encoding="utf-8")
            code = await asyncio.to_thread(run_command, command, self.workspace.path)
        except Exception as exc:  # noqa: BLE001 - surface any launch failure to the user
            self._next_audit_running = False
            self.notify(f"Next audit failed: {exc}", severity="error")
            return
        self._next_audit_running = False
        if code != 0:
            self.notify(f"Next audit exited with code {code}. Backup at {backup.name}.", severity="error")
            return
        self.show_workspace_overview()
        self.notify(f"Next audited by Sonnet. Backup saved to {backup.name}.", timeout=8)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-audit":
            event.stop()
            self.action_audit_next()

    def action_tool(self) -> None:
        self.query_one("#right-switcher", ContentSwitcher).current = "agents-view"
        self.tool_picker_open = False
        self.preview_mode = False
        if self.session_widget is not None:
            self.call_after_refresh(self.session_widget.query_one(DataTable).focus)

    def action_detach_tool(self) -> None:
        """Return to the workspace while leaving the terminal process running."""
        self.show_workspace_overview()

    def action_kill_tool(self) -> None:
        """Stop the active terminal process, if any."""
        if self.session_widget is not None and self.query_one("#right-switcher", ContentSwitcher).current == "agents-view":
            self.session_widget.stop_selected()

    def action_launch_tool(self, index: int) -> None:
        tools = list(self.config.tools)
        if index >= len(tools):
            return
        name = tools[index]
        command = self.config.tools[name]
        ensure_tool_file(self.workspace, name, command)
        self.action_tool()
        if self.session_widget is None:
            return
        self.session_widget.launch_background(name)

    def action_move_up(self) -> None:
        if isinstance(self.focused, TextArea):
            return
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("up")
            return
        if self.focus_area in ("last", "next"):
            self._scroll_overview_panel(f"{self.focus_area}-panel", "up")
            return
        focused = self.focused
        if isinstance(focused, DirectoryTree):
            focused.action_cursor_up()
            return
        self.query_one("#file-tree", DirectoryTree).focus()

    def action_move_down(self) -> None:
        if isinstance(self.focused, TextArea):
            return
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("down")
            return
        if self.focus_area in ("last", "next"):
            self._scroll_overview_panel(f"{self.focus_area}-panel", "down")
            return
        focused = self.focused
        if isinstance(focused, DirectoryTree):
            focused.action_cursor_down()
            return
        self.query_one("#file-tree", DirectoryTree).focus()

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
            if self.focus_area == "next":
                self.focus_area = "last"
                self.update_focus_styles()
            elif self.focus_area == "last":
                self.action_focus_tree()
            else:
                self.action_focus_tree()
        elif key == "right":
            if self.focus_area == "last":
                self.action_focus_next_overview_panel()
            elif self.focus_area == "files" and not self.preview_mode:
                self.focus_area = "last"
                self.update_focus_styles()
            else:
                self.action_focus_preview()
        elif key == "up":
            self.action_move_up()
        elif key == "down":
            self.action_move_down()
        elif key == "pageup":
            self.action_page_up()
        elif key == "pagedown":
            self.action_page_down()
        elif key == "home":
            self.action_scroll_home()
        elif key == "end":
            self.action_scroll_end()
        elif key == "enter":
            self.action_select_focused()

    def _scroll_overview_panel(self, panel_id: str, direction: str) -> None:
        scroll_id = "last-scroll" if panel_id == "last-panel" else "next-scroll"
        scroller = self.query_one(f"#{scroll_id}", VerticalScroll)
        actions = {
            "up": scroller.scroll_up,
            "down": scroller.scroll_down,
            "page_up": scroller.scroll_page_up,
            "page_down": scroller.scroll_page_down,
            "home": scroller.scroll_home,
            "end": scroller.scroll_end,
        }
        actions[direction]()

    def action_page_up(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("page_up")
        elif self.focus_area == "last":
            self._scroll_overview_panel("last-panel", "page_up")
        elif self.focus_area == "next":
            self._scroll_overview_panel("next-panel", "page_up")

    def action_page_down(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("page_down")
        elif self.focus_area in ("last", "next"):
            self._scroll_overview_panel(f"{self.focus_area}-panel", "page_down")

    def action_scroll_home(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("home")
        elif self.focus_area in ("last", "next"):
            self._scroll_overview_panel(f"{self.focus_area}-panel", "home")

    def action_scroll_end(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("end")
        elif self.focus_area in ("last", "next"):
            self._scroll_overview_panel(f"{self.focus_area}-panel", "end")

    def scroll_preview(self, direction: str) -> None:
        preview = self.current_preview_widget()
        if isinstance(preview, MarkdownViewer):
            actions = {
                "up": preview.action_scroll_up,
                "down": preview.action_scroll_down,
                "page_up": preview.action_page_up,
                "page_down": preview.action_page_down,
                "home": preview.action_scroll_home,
                "end": preview.action_scroll_end,
            }
        else:
            actions = {
                "up": preview.scroll_up,
                "down": preview.scroll_down,
                "page_up": preview.scroll_page_up,
                "page_down": preview.scroll_page_down,
                "home": preview.scroll_home,
                "end": preview.scroll_end,
            }
        try:
            actions[direction]()
        except SkipAction:
            return

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

    def _check_pending_weeks(self) -> None:
        workspace = self.workspace
        pending = find_pending_weeks(workspace.days_dir, workspace.weeks_dir)
        for year, week in pending:
            week_path = workspace.week_file(year, week)
            if not week_path.exists():
                auto_generate_draft(workspace.name, workspace.days_dir, workspace.weeks_dir, year, week)
        self.pending_weeks = pending
        if pending:
            label = week_label(*pending[0])
            self.notify(
                f"Weekly draft ready: {label}\nPress W to review and add to worklog.",
                timeout=10,
            )

    def action_weekly_review(self) -> None:
        if not self.pending_weeks:
            if self.workspace.worklog_file.exists():
                self.show_markdown_preview(self.workspace.worklog_file.read_text(encoding="utf-8"))
            else:
                self.notify("No pending weekly drafts. Work some sessions first!", severity="information")
            return
        year, week = self.pending_weeks[0]
        fields = read_week_draft(self.workspace.weeks_dir, year, week)
        if fields is None:
            auto_generate_draft(
                self.workspace.name,
                self.workspace.days_dir,
                self.workspace.weeks_dir,
                year,
                week,
            )
            fields = read_week_draft(self.workspace.weeks_dir, year, week) or ("", "", "")
        summary, highlights, carry_forwards = fields
        self.push_screen(
            WeeklyReviewScreen(year, week, summary, highlights, carry_forwards),
            lambda result: self._save_weekly(result, year, week),
        )

    def _save_weekly(self, result: dict[str, str] | None, year: int, week: int) -> None:
        if result is None:
            return
        append_week_to_worklog(
            self.workspace.worklog_file,
            year,
            week,
            result["summary"],
            result["highlights"],
            result["carry_forwards"],
        )
        finalize_week_draft(self.workspace.weeks_dir, year, week)
        self.pending_weeks = [w for w in self.pending_weeks if w != (year, week)]
        if self.pending_weeks:
            next_label = week_label(*self.pending_weeks[0])
            self.notify(f"Saved. Another draft ready: {next_label} — press W to continue.", timeout=8)
        else:
            self.notify("Worklog updated.")
        self.action_refresh()

    def action_log_browser(self) -> None:
        def on_result(path: Path | None) -> None:
            if path is not None:
                self.edit_path(path)
        self.push_screen(LogBrowserScreen(self.workspace), on_result)

    def action_knowledge(self) -> None:
        if workspace_mode(self.workspace) != "study":
            self.notify("Knowledge lookup is available in Study workspaces.", severity="information")
            return
        initial = self.active_file if self.active_file and is_markdown_file(self.active_file) else None
        self._open_knowledge(initial)

    def _open_knowledge(self, initial: Path | None) -> None:
        def on_result(path: Path | None) -> None:
            if path is not None:
                self.edit_path(path)
                self._open_knowledge(path)
        self.push_screen(KnowledgeScreen(self.workspace.path, initial), on_result)

    def action_handoff(self) -> None:
        workspace = self.workspace
        tools = [*self.tools_launched, *self.run_ledger.tools_launched]
        kind = workspace_type(workspace) or "regular"
        git_status = git_status_short(workspace.path) if kind == "code" else ""
        changed_files = changed_files_from_status(git_status)
        evidence = (
            f"Files changed:\n{chr(10).join(f'- {item}' for item in changed_files) or '- None detected'}\n\n"
            f"Tools launched:\n{chr(10).join(f'- {item}' for item in tools) or '- None tracked'}\n\n"
            f"Git status:\n{git_status or 'No changes detected.'}"
            if kind == "code"
            else ""
        )
        next_template = (
            preview_file(workspace.next_file, limit=3000)
            if workspace.next_file.exists()
            else "# Next\n\n- "
        )
        draft = self.run_ledger.merged_draft(next_template)
        summary, done, open_items = parse_last_sections(draft.last)
        next_text = draft.next
        self.push_screen(
            HandoffScreen(workspace.name, summary, done, open_items, next_text, evidence),
            self.save_handoff,
        )

    def save_handoff(self, result: dict[str, str] | None) -> None:
        if result is None:
            self.action_refresh()
            return
        if not any(result[key].strip() for key in ("summary", "done", "open", "next")):
            self.notify("Handoff empty; nothing saved.")
            return
        if not result["summary"].strip():
            self.notify("Summary is blank — saved with 'Not recorded'. Edit the session log to add one.", severity="warning", timeout=8)
        ended_at = now_local()
        save_workspace_handoff(
            workspace=self.workspace,
            started_at=self.started_at,
            ended_at=ended_at,
            files_opened=self.files_opened,
            tools_launched=[*self.tools_launched, *self.run_ledger.tools_launched],
            fields=result,
        )
        self.run_ledger.consume()
        self.notify("Saved handoff, session log, and day log")
        self.show_workspace_overview()
        if self.quit_after_handoff:
            self.quit_after_handoff = False
            self.run_worker(self._shutdown_and_exit(), exclusive=False)

    def action_quit(self) -> None:
        draft = self.workspace.draft_file
        pending = draft.exists() and draft_has_content(draft.read_text(encoding="utf-8"))
        pending = pending or self.run_ledger.has_pending
        pending = pending or any(s.state in {"starting", "running"} for s in self.session_manager.sessions)
        if not pending:
            self.run_worker(self._shutdown_and_exit(), exclusive=False)
            return
        self.push_screen(QuitAgentScreen(), self._finish_quit_choice)

    def _finish_quit_choice(self, choice: str) -> None:
        if choice == "handoff":
            self.quit_after_handoff = True
            self.action_handoff()
        elif choice == "discard":
            self.run_worker(self._shutdown_and_exit(), exclusive=False)

    async def _shutdown_and_exit(self) -> None:
        if self.session_widget is not None:
            await self.session_widget.shutdown_async()
        else:
            await asyncio.to_thread(self.session_manager.shutdown)
        self.exit()
