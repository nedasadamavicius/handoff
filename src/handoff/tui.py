from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, DirectoryTree, Footer, Input, Label, Markdown, MarkdownViewer, TextArea

from handoff.config import AppConfig
from handoff.git import changed_files_from_status, git_status_short
from handoff.launcher import LaunchError, claude_finalize_command, codex_finalize_command, editor_command, run_command, tool_command
from handoff.handoff import parse_draft_or_files, parse_last_sections
from handoff.session import now_local, render_session_log, session_filename, update_day_log
from handoff.theme import ensure_themes_dir, register_all_themes
from handoff.workspace import Workspace, ensure_tool_file, ensure_workspace_files, infer_workspace_type, preview_file, workspace_type


HIDDEN_TREE_NAMES = {".git", ".handoff", "__pycache__", ".pytest_cache", ".claude"}
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}


class WorkspaceDirectoryTree(DirectoryTree):
    def filter_paths(self, paths):
        return [
            path
            for path in paths
            if path.name not in HIDDEN_TREE_NAMES and path.suffix not in {".pyc", ".pyo"}
        ]

    def on_key(self, event) -> None:
        if event.key in {"left", "right", "up", "down", "pageup", "pagedown", "home", "end", "enter"}:
            event.stop()
            self.app.handle_navigation_key(event.key)


class HandoffScreen(ModalScreen[dict[str, str] | None]):
    FIELD_ORDER = [
        ("page-summary", "handoff-summary", "Summary"),
        ("page-done", "handoff-done", "Completed"),
        ("page-open", "handoff-open", "Open issues"),
        ("page-next", "handoff-next", "Next session"),
    ]

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

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+right", "next_field", "Next Field", show=False, priority=True),
        Binding("ctrl+left", "previous_field", "Previous Field", show=False, priority=True),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, workspace_name: str, summary: str, done: str, open_items: str, next_template: str, evidence: str = "") -> None:
        super().__init__()
        self.workspace_name = workspace_name
        self.summary = summary
        self.done = done
        self.open_items = open_items
        self.next_template = next_template
        self.evidence = evidence
        self.current_field_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="handoff-dialog"):
            yield Label(f"Session Handoff - {self.workspace_name}", id="handoff-title")
            yield Label("", id="handoff-page-status")
            with ContentSwitcher(initial="page-summary", id="handoff-pages"):
                with Vertical(id="page-summary", classes="handoff-page"):
                    yield Label("Summary", classes="field-label")
                    yield TextArea(
                        self.summary,
                        id="handoff-summary",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-done", classes="handoff-page"):
                    yield Label("Completed", classes="field-label")
                    yield TextArea(
                        self.done,
                        id="handoff-done",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-open", classes="handoff-page"):
                    yield Label("Open issues", classes="field-label")
                    yield TextArea(
                        self.open_items,
                        id="handoff-open",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                with Vertical(id="page-next", classes="handoff-page"):
                    yield Label("Next session", classes="field-label")
                    yield TextArea(
                        self.next_template,
                        id="handoff-next",
                        classes="handoff-field",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                if self.evidence:
                    with Vertical(id="page-evidence", classes="handoff-page"):
                        yield Label("Evidence", classes="field-label")
                        yield TextArea(
                            self.evidence,
                            id="handoff-evidence",
                            classes="handoff-field",
                            read_only=True,
                            soft_wrap=True,
                            show_line_numbers=False,
                        )
            with Horizontal(id="handoff-footer"):
                yield Label("Ctrl+Left/Right switch fields\nCtrl+S save\nEsc cancel", id="handoff-help")
                with Horizontal(id="handoff-buttons"):
                    yield Button("Cancel", id="cancel", classes="handoff-button")
                    yield Button("Save", id="save", variant="primary", classes="handoff-button")

    def on_mount(self) -> None:
        self.show_field(0)

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

    def show_field(self, index: int) -> None:
        self.current_field_index = index % len(self.FIELD_ORDER)
        page_id, field_id, label = self.FIELD_ORDER[self.current_field_index]
        self.query_one("#handoff-pages", ContentSwitcher).current = page_id
        self.query_one("#handoff-page-status", Label).update(f"{label} ({self.current_field_index + 1}/{len(self.FIELD_ORDER)})")
        self.query_one(f"#{field_id}", TextArea).focus()

    def action_next_field(self) -> None:
        self.show_field(self.current_field_index + 1)

    def action_previous_field(self) -> None:
        self.show_field(self.current_field_index - 1)


class NewFileScreen(ModalScreen[str | None]):
    CSS = """
    NewFileScreen {
        align: center middle;
    }

    #new-file-dialog {
        width: 60;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #new-file-title {
        height: auto;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #new-file-input {
        margin-top: 1;
    }

    #new-file-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    .new-file-button {
        width: 9;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory

    def compose(self) -> ComposeResult:
        with Vertical(id="new-file-dialog"):
            yield Label(f"New file in {self.directory.name}/", id="new-file-title")
            yield Input(placeholder="filename.md", id="new-file-input")
            with Horizontal(id="new-file-buttons"):
                yield Button("Cancel", id="cancel", classes="new-file-button")
                yield Button("Create", id="create", variant="primary", classes="new-file-button")

    def on_mount(self) -> None:
        self.query_one("#new-file-input", Input).focus()

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
        filename = self.query_one("#new-file-input", Input).value.strip()
        self.dismiss(filename if filename else None)


def strip_handoff_frontmatter(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return
    try:
        _, _frontmatter, body = text.split("---\n", 2)
    except ValueError:
        return
    path.write_text(body.lstrip(), encoding="utf-8")


def is_markdown_file(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_SUFFIXES


def strip_first_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).lstrip()
    return markdown


def strip_first_subheading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].startswith("## "):
        return "\n".join(lines[1:]).lstrip()
    return markdown


def render_last_markdown(fields: dict[str, str]) -> str:
    parts = ["# Current Session Summary"]
    parts.append("## Summary\n\n" + (fields["summary"].strip() or "Not recorded."))
    parts.append("## Completed\n\n" + normalize_list_text(fields["done"]))
    parts.append("## Open Issues\n\n" + normalize_list_text(fields["open"]))
    if fields.get("evidence", "").strip():
        parts.append("## Evidence\n\n```text\n" + fields["evidence"].strip() + "\n```")
    return "\n\n".join(parts)


def render_next_markdown(text: str) -> str:
    return "# Next\n\n" + normalize_list_text(text)


def normalize_list_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "- None"
    lines = []
    for line in cleaned.splitlines():
        item = line.strip()
        if not item:
            continue
        lines.append(item if item.startswith(("-", "*")) else f"- {item}")
    return "\n".join(lines) or "- None"


def strip_next_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].strip().lower() in {"# next", "## next.md"}:
        return "\n".join(lines[1:]).lstrip()
    return strip_first_heading(markdown)


def deduplicate_next_lines(text: str) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized:
            if merged and merged[-1] != "":
                merged.append("")
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(line)
    while merged and not merged[-1].strip():
        merged.pop()
    return "\n".join(merged)


def merge_next_text(existing: str, incoming: str) -> str:
    existing_body = strip_next_heading(existing).strip()
    incoming_body = strip_next_heading(incoming).strip()
    if not incoming_body:
        return existing_body
    if not existing_body or existing_body == "- Define the next action.":
        return deduplicate_next_lines(incoming_body)

    return deduplicate_next_lines(existing_body + "\n" + incoming_body)


class WorkspaceShell(App):
    TITLE = "handoff"

    CSS = """
    #root {
        height: 100%;
    }

    #browser {
        width: 40;
        border: solid $panel;
    }

    #browser.focused-pane {
        border: heavy $primary;
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

    #last-container {
        width: 1fr;
        height: 1fr;
        border: round $success;
    }

    #next-container {
        width: 1fr;
        height: 1fr;
        border: round $warning;
    }

    #last-header {
        height: auto;
        padding: 0 1;
        text-style: bold;
        color: $success;
        border-bottom: solid $success;
    }

    #next-header {
        height: auto;
        padding: 0 1;
        text-style: bold;
        color: $warning;
        border-bottom: solid $warning;
    }

    #last-panel {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }

    #next-panel {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }

    #file-tree {
        height: 1fr;
    }

    #preview {
        height: 100%;
        border: round $secondary;
        padding: 1;
    }

    #text-preview {
        height: 100%;
        border: round $secondary;
    }

    #preview.focused-pane {
        border: heavy $accent;
    }

    #text-preview.focused-pane {
        border: heavy $accent;
    }

    DirectoryTree:focus {
        border: heavy $primary;
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
        Binding("t", "tool", "Tool"),
        Binding("1", "launch_tool(0)", "Tool 1", show=False),
        Binding("2", "launch_tool(1)", "Tool 2", show=False),
        Binding("3", "launch_tool(2)", "Tool 3", show=False),
        Binding("4", "launch_tool(3)", "Tool 4", show=False),
        Binding("5", "launch_tool(4)", "Tool 5", show=False),
        Binding("left", "focus_tree", "Files", show=False, priority=True),
        Binding("right", "focus_preview", "Preview", show=False, priority=True),
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
        Binding("enter", "select_focused", "Select", show=False),
        Binding("c", "new_file", "New File"),
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

    def compose(self) -> ComposeResult:
        with Horizontal(id="root"):
            with Vertical(id="browser"):
                yield WorkspaceDirectoryTree(str(self.workspace.path), id="file-tree")
            with Vertical(id="right-pane"):
                with ContentSwitcher(id="right-switcher", initial="overview-view"):
                    with Horizontal(id="overview-view"):
                        with Vertical(id="last-container"):
                            yield Label("Last Session", id="last-header")
                            yield Markdown("", id="last-panel")
                        with Vertical(id="next-container"):
                            yield Label("What's Next", id="next-header")
                            yield Markdown("", id="next-panel")
                    with Vertical(id="preview-view"):
                        yield MarkdownViewer("", show_table_of_contents=False, id="preview")
                    with Vertical(id="text-preview-view"):
                        yield TextArea("", read_only=True, show_cursor=False, show_line_numbers=False, id="text-preview")
        yield Footer()

    def on_mount(self) -> None:
        ensure_themes_dir(self.config.themes_dir)
        register_all_themes(self, self.config)
        self.query_one("#file-tree", DirectoryTree).focus()
        if workspace_type(self.workspace) is None:
            ensure_workspace_files(self.workspace, workspace_kind=infer_workspace_type(self.workspace))
        else:
            ensure_workspace_files(self.workspace, workspace_kind=workspace_type(self.workspace) or "regular")
        self.sub_title = workspace_type(self.workspace) or infer_workspace_type(self.workspace)
        self.show_workspace_overview()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        text_area_actions = {
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
        if isinstance(self.focused, TextArea) and action in text_area_actions:
            return False
        return True

    def show_workspace_overview(self) -> None:
        workspace = self.workspace
        latest = workspace.last_handoff()
        next_text = (
            preview_file(workspace.next_file, limit=1500)
            if workspace.next_file.exists()
            else "No next actions yet.\n\nPress **n** to add some."
        )
        latest_text = (
            latest.body[:2500]
            if latest
            else "No session recorded yet.\n\nPress **h** after working to save your first handoff."
        )
        self.query_one("#right-switcher", ContentSwitcher).current = "overview-view"
        self.query_one("#last-panel", Markdown).update(strip_first_subheading(strip_first_heading(latest_text)))
        self.query_one("#next-panel", Markdown).update(strip_first_heading(next_text))
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
        if self.focus_area != "files":
            return
        target_dir = self._get_cursor_directory()

        def on_result(filename: str | None) -> None:
            if not filename:
                return
            new_path = target_dir / filename
            if new_path.exists():
                self.notify(f"{filename} already exists.", severity="warning")
                return
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                new_path.touch()
            except OSError as exc:
                self.notify(str(exc), severity="error")
                return
            self.active_file = new_path
            self.action_refresh()

        self.push_screen(NewFileScreen(target_dir), on_result)

    def action_edit(self) -> None:
        if self.active_file is None:
            self.notify("Select a file first.", severity="warning")
            return
        self.edit_path(self.active_file)

    def edit_path(self, path: Path) -> None:
        command = editor_command(self.config, path)
        try:
            with self.suspend():
                run_command(command, cwd=self.workspace.path, shell=True)
        except LaunchError as exc:
            self.notify(str(exc), severity="error")
            return
        self.action_refresh()

    def action_edit_workspace_context(self) -> None:
        self.edit_path(self.workspace.workspace_file)

    def action_edit_last(self) -> None:
        strip_handoff_frontmatter(self.workspace.last_file)
        self.edit_path(self.workspace.last_file)

    def action_edit_next(self) -> None:
        self.edit_path(self.workspace.next_file)

    def action_tool(self) -> None:
        if not self.config.tools:
            self.notify("No tools configured.", severity="warning")
            return
        lines = [
            "# Tool Launcher",
            "",
            "Press a number to launch a tool in the active workspace.",
            "",
        ]
        for index, (name, command) in enumerate(self.config.tools.items(), start=1):
            if index > 5:
                break
            lines.append(f"{index}. **{name}** - `{command}`")
        lines.extend(
            [
                "",
                f"Workspace: `{self.workspace.name}`",
                "",
                "Press `r` to return to the workspace overview.",
            ]
        )
        self.show_single_panel("\n".join(lines))
        self.tool_picker_open = True

    def action_launch_tool(self, index: int) -> None:
        if not self.tool_picker_open:
            return
        tools = list(self.config.tools)
        if index >= len(tools):
            return
        name = tools[index]
        command = tool_command(self.config, name)
        self.tools_launched.append(name)
        try:
            ensure_tool_file(self.workspace, name, command)
            with self.suspend():
                run_command(command, cwd=self.workspace.path, shell=True)
                for finalizer in (
                    codex_finalize_command(name, command),
                    claude_finalize_command(name, command),
                ):
                    if finalizer is not None:
                        run_command(finalizer, cwd=self.workspace.path, shell=True)
        except LaunchError as exc:
            self.tools_launched.pop()
            self.notify(str(exc), severity="error")
            return
        self.tool_picker_open = False
        self.action_handoff()

    def action_move_up(self) -> None:
        if isinstance(self.focused, TextArea):
            return
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("up")
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

    def update_focus_styles(self) -> None:
        browser = self.query_one("#browser", Vertical)
        markdown_preview = self.query_one("#preview", MarkdownViewer)
        text_preview = self.query_one("#text-preview", TextArea)
        browser.set_class(self.focus_area == "files", "focused-pane")
        markdown_preview.set_class(self.focus_area == "preview" and self.active_preview == "markdown", "focused-pane")
        text_preview.set_class(self.focus_area == "preview" and self.active_preview == "text", "focused-pane")

    def handle_navigation_key(self, key: str) -> None:
        if isinstance(self.focused, TextArea):
            return
        if key == "left":
            self.action_focus_tree()
        elif key == "right":
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

    def action_page_up(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("page_up")

    def action_page_down(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("page_down")

    def action_scroll_home(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("home")

    def action_scroll_end(self) -> None:
        if self.focus_area == "preview" and self.preview_mode:
            self.scroll_preview("end")

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

    def action_handoff(self) -> None:
        workspace = self.workspace
        tools = self.tools_launched
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
        next_template = preview_file(workspace.next_file, limit=3000) if workspace.next_file.exists() else "# Next\n\n- "
        summary, done, open_items = "", "- ", "- "
        next_text = strip_first_heading(next_template)
        if workspace.draft_file.exists():
            draft = parse_draft_or_files(workspace.draft_file.read_text(encoding="utf-8"), next_template)
            summary, done, open_items = parse_last_sections(draft.last)
            if draft.next.strip():
                next_text = merge_next_text(next_template, draft.next)
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
        ended_at = now_local()
        last = render_last_markdown(result)
        next_text = render_next_markdown(result["next"])
        session_name = session_filename(ended_at)
        self.workspace.sessions_dir.mkdir(parents=True, exist_ok=True)
        session_path = self.workspace.sessions_dir / session_name
        counter = 2
        while session_path.exists():
            session_name = session_filename(ended_at).removesuffix(".md") + f"-{counter}.md"
            session_path = self.workspace.sessions_dir / session_name
            counter += 1
        session_path.write_text(
            render_session_log(
                workspace=self.workspace.name,
                started_at=self.started_at,
                ended_at=ended_at,
                files_opened=self.files_opened,
                tools_launched=self.tools_launched,
                summary=result["summary"],
                completed=result["done"],
                open_issues=result["open"],
                evidence=result.get("evidence", ""),
            ),
            encoding="utf-8",
        )
        update_day_log(
            path=self.workspace.day_file(ended_at.date()),
            workspace=self.workspace.name,
            ended_at=ended_at,
            session_file=session_name,
            summary=result["summary"],
            completed=result["done"],
            open_issues=result["open"],
        )
        self.workspace.last_file.write_text(last.rstrip() + "\n", encoding="utf-8")
        if next_text.strip():
            self.workspace.next_file.write_text(next_text.rstrip() + "\n", encoding="utf-8")
        if self.workspace.draft_file.exists():
            self.workspace.draft_file.unlink()
        self.notify("Saved handoff, session log, and day log")
        self.show_workspace_overview()
