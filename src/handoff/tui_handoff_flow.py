from __future__ import annotations

import asyncio
from pathlib import Path

from handoff.documents import (
    is_markdown_file,
)
from handoff.git import changed_files_from_status, git_status_short
from handoff.handoff import draft_has_content, parse_last_sections
from handoff.note_sync import has_unsynced, sync_for_repo
from handoff.session import now_local
from handoff.source_tags import format_numbered, number_files, resolve_source_tags
from handoff.tui_agents import QuitAgentScreen
from handoff.tui_logs import LogBrowserScreen
from handoff.tui_screens import (
    HandoffScreen,
    KnowledgeScreen,
    SyncScreen,
    WeeklyReviewScreen,
)
from handoff.webdav import OfflineError, SyncError, load_password
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
    preview_file,
    workspace_mode,
    workspace_type,
)


class HandoffFlowMixin:
    """Handoff saving, weekly review, note sync and quitting for the workspace shell."""

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
        if self.config.source_tags:
            changed_files = number_files(changed_files)
            files_block = format_numbered(changed_files) or "- None detected"
        else:
            files_block = chr(10).join(f"- {item}" for item in changed_files) or "- None detected"
        evidence = (
            f"Files changed:\n{files_block}\n\n"
            f"Tools launched:\n{chr(10).join(f'- {item}' for item in tools) or '- None tracked'}\n\n"
            f"Git status:\n{git_status or 'No changes detected.'}"
            if kind == "code"
            else ""
        )
        next_template = (
            preview_file(workspace.next_file, limit=3000) if workspace.next_file.exists() else "# Next\n\n- "
        )
        draft = self.run_ledger.merged_draft(next_template)
        summary, done, open_items = parse_last_sections(draft.last)
        if self.config.source_tags:
            done, dropped = resolve_source_tags(done, changed_files)
            if dropped:
                self.notify(
                    f"Dropped source tags not in changed files: {', '.join(dropped)}", severity="warning", timeout=8
                )
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
            self.notify(
                "Summary is blank — saved with 'Not recorded'. Edit the session log to add one.",
                severity="warning",
                timeout=8,
            )
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
        self.run_worker(self._finish_save(), exclusive=False)

    async def _finish_save(self) -> None:
        if await self._sync_blocking("Syncing handoff notes"):
            self.show_workspace_overview()
        if self.quit_after_handoff:
            self.quit_after_handoff = False
            await self._shutdown_and_exit()

    @property
    def _sync_enabled(self) -> bool:
        return self.config.sync is not None and bool(load_password(self.config.root))

    async def _sync_blocking(self, title: str) -> bool:
        """Sync behind a modal that cannot be dismissed. Offline or errors end it with a notice."""
        if not self._sync_enabled:
            return False
        screen = SyncScreen(title)
        await self.push_screen(screen)

        def progress(message: str) -> None:
            self.call_from_thread(screen.set_detail, message)

        try:
            report = await asyncio.to_thread(
                sync_for_repo, self.config.root, self.config.sync, self.workspace.path, progress
            )
        except OfflineError:
            self.notify(
                "Offline: notes will sync next time handoff opens with a connection.", severity="warning", timeout=8
            )
            return False
        except SyncError as exc:
            self.notify(f"Sync error: {exc}", severity="error", timeout=10)
            return False
        finally:
            if self.screen is screen:
                self.pop_screen()
        if report is None:
            return False
        if report.conflicts:
            self.notify(
                f"Sync conflict in {', '.join(report.conflicts)}; remote copy saved as *.conflict.md",
                severity="warning",
                timeout=10,
            )
        else:
            self.notify(f"Synced: {report.summary()}")
        return True

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
        if self._sync_enabled and has_unsynced(self.workspace.meta):
            await self._sync_blocking("Syncing before exit")
        if self.session_widget is not None:
            await self.session_widget.shutdown_async()
        else:
            await asyncio.to_thread(self.session_manager.shutdown)
        self.exit()
