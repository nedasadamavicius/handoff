from __future__ import annotations

import shlex
import threading
import time
from typing import TYPE_CHECKING

import pyte
from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from handoff.pty_session import PtySession, PtyUnavailable

if TYPE_CHECKING:
    from handoff.config import AppConfig


_RICH_COLORS = {"black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"}


class TerminalScreen(pyte.Screen):
    """Return terminal query replies to the child, not the outer terminal."""

    def __init__(self, columns: int, lines: int, session: PtySession) -> None:
        self.session = session
        super().__init__(columns, lines)

    def write_process_input(self, data: str) -> None:
        self.session.write(data.encode("utf-8"))


def _rich_color(name: str | None) -> str | None:
    """Map a pyte colour name to something Rich can parse (or None)."""
    if not name or name == "default":
        return None
    if name == "brown":  # pyte's name for yellow
        return "yellow"
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "#" + name
    if name in _RICH_COLORS:
        return name
    if name.startswith("bright"):
        base = name[6:]
        if base in _RICH_COLORS:
            return "bright_" + base
    return None


class TerminalPane(Widget):
    """Terminal widget hosting one agent CLI in a PTY."""

    can_focus = True
    DEFAULT_CSS = "TerminalPane { width: 1fr; height: 1fr; overflow: hidden hidden; }"

    def __init__(
        self, config: AppConfig, workspace_path, *, id: str = "terminal-pane"
    ) -> None:
        """Initialize the terminal pane.

        Args:
            config: Application configuration with tools mapping.
            workspace_path: Working directory for spawned processes.
            id: Widget ID.
        """
        super().__init__(id=id)
        self.config = config
        self._cwd = str(workspace_path)
        self._pty: PtySession | None = None
        self._screen: pyte.Screen | None = None
        self._stream: pyte.ByteStream | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._screen_lock = threading.Lock()
        self._pty_running = False
        self._launched = False
        self._error: str | None = None
        self._dirty = threading.Event()
        self._rows = 24
        self._cols = 80

    def on_mount(self) -> None:
        # Poll a dirty flag: the reader never waits for the UI and the last
        # update in a burst is always painted, even if the child goes idle.
        self.set_interval(0.05, self._refresh_from_reader)

    def launch(self, name: str) -> bool:
        """Launch an agent by name.

        Args:
            name: Tool name from config.tools.

        Returns:
            True on success, False if already running or on error.
        """
        if self._pty_running:
            return False

        try:
            command = self.config.tools[name]
            argv = shlex.split(command, posix=False)

            self._pty = PtySession()
            self._pty.spawn(argv, cwd=self._cwd, rows=self._rows, cols=self._cols)

            self._screen = TerminalScreen(self._cols, self._rows, self._pty)
            self._stream = pyte.ByteStream(self._screen)

            self._pty_running = True
            self._launched = True
            self._error = None
            self._stop_reader = threading.Event()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                args=(self._pty, self._stream, self._stop_reader), daemon=True
            )
            self._reader_thread.start()
            self.refresh()
            try:
                self.focus()
            except Exception:
                # No active app context yet
                pass
            return True
        except (PtyUnavailable, FileNotFoundError, KeyError) as exc:
            self._pty_running = False
            self._error = str(exc)
            self.refresh()
            return False
        except Exception as exc:
            self._pty_running = False
            self._error = f"Could not start {name}: {exc}"
            self.refresh()
            return False

    def is_running(self) -> bool:
        """Check if the PTY is currently running.

        Returns:
            True if running, False otherwise.
        """
        return self._pty_running

    @property
    def last_error(self) -> str | None:
        """Most recent launch or terminal-read error, if any."""
        return self._error

    def kill(self) -> None:
        """Stop the terminal session. Idempotent."""
        if self._stop_reader is not None:
            self._stop_reader.set()
        if self._pty is not None:
            self._pty.terminate()
        self._pty_running = False
        self.refresh()

    async def shutdown(self) -> None:
        """Gracefully shutdown, joining the reader thread."""
        self.kill()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

    @property
    def has_live_runs(self) -> bool:
        """Compatibility property for app cleanup."""
        return self.is_running()

    def snapshot_active(self) -> None:
        """No-op; exists for app-cleanup compatibility."""
        pass

    def render(self) -> Text:
        """Render the terminal state as a Rich Text.

        Returns:
            Text renderable.
        """
        if not self._launched:
            if self._error:
                return Text(self._error)
            # Idle state: show tool list
            lines = ["Terminal • select an agent to launch"]
            for idx, name in enumerate(self.config.tools.keys(), start=1):
                lines.append(f"{idx}  {name}")
            lines.append("")
            lines.append("press 1-N to launch · Ctrl+T detach · Ctrl+K kill")
            return Text("\n".join(lines))

        if not self._pty_running:
            if self._error:
                return Text(self._error + "\npress 1-N to relaunch")
            # Ended state
            return Text("session ended — press 1-N to relaunch")

        # Running: render pyte screen
        if self._screen is None:
            return Text("")

        with self._screen_lock:
            cursor = (self._screen.cursor.y, self._screen.cursor.x)
            cursor_visible = self.has_focus and not self._screen.cursor.hidden
            lines = [
                [self._screen.buffer[y][x] for x in range(self._screen.columns)]
                for y in range(self._screen.lines)
            ]

        result = Text(no_wrap=True, overflow="crop")
        styles: dict[tuple[object, ...], Style] = {}
        for row_index, row in enumerate(lines):
            for column, char in enumerate(row):
                key = (char.fg, char.bg, char.bold, char.italics, char.underscore, char.reverse)
                style = styles.get(key)
                if style is None:
                    style = styles[key] = Style(
                        color=_rich_color(char.fg),
                        bgcolor=_rich_color(char.bg),
                        bold=char.bold,
                        italic=char.italics,
                        underline=char.underscore,
                        reverse=char.reverse,
                    )
                if cursor_visible and cursor == (row_index, column):
                    style = style + Style(reverse=not char.reverse)
                result.append(char.data, style=style)
            if row_index < len(lines) - 1:
                result.append("\n")
        return result

    def on_key(self, event) -> None:
        """Forward keyboard input to the PTY.

        Args:
            event: Textual key event.
        """
        if not self._pty_running:
            return

        # Key translation table
        key_map = {
            "enter": b"\r",
            "backspace": b"\x7f",
            "tab": b"\t",
            "escape": b"\x1b",
            "up": b"\x1b[A",
            "down": b"\x1b[B",
            "right": b"\x1b[C",
            "left": b"\x1b[D",
            "home": b"\x1b[H",
            "end": b"\x1b[F",
            "pageup": b"\x1b[5~",
            "pagedown": b"\x1b[6~",
            "delete": b"\x1b[3~",
        }

        data = None

        if event.key in key_map:
            data = key_map[event.key]
        elif event.key.startswith("ctrl+") and len(event.key) > 5:
            # ctrl+<letter>
            letter = event.key[5]
            data = bytes([ord(letter) & 0x1F])
        elif event.character and len(event.character) == 1 and ord(event.character) >= 32:
            # Printable character
            data = event.character.encode("utf-8")

        if data is not None and self._pty is not None:
            self._pty.write(data)
            event.stop()
            event.prevent_default()

    def on_resize(self, event) -> None:
        """Handle terminal resize.

        Args:
            event: Textual resize event.
        """
        cols = self.content_size.width
        rows = self.content_size.height
        # Hidden/minimized widgets must not collapse the child's terminal.
        if cols <= 0 or rows <= 0:
            return

        self._rows = rows
        self._cols = cols

        if self._pty_running and self._screen is not None and self._pty is not None:
            with self._screen_lock:
                self._screen.resize(rows, cols)
            self._pty.resize(rows, cols)
        self.refresh()

    def on_paste(self, event) -> None:
        if not self._pty_running or self._pty is None:
            return
        data = event.text.encode("utf-8")
        if self._screen is not None and 2004 << 5 in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._pty.write(data)
        event.stop()
        event.prevent_default()

    def _request_refresh(self) -> None:
        """Mark output dirty without blocking the PTY reader on the UI."""
        self._dirty.set()

    def _refresh_from_reader(self) -> None:
        if self._dirty.is_set():
            self._dirty.clear()
            self.refresh()

    def _reader_loop(self, session, stream, stop) -> None:
        """Background thread: read from PTY and feed to pyte."""
        try:
            while not stop.is_set():
                data = session.read()
                if stop.is_set():
                    break
                if data:
                    with self._screen_lock:
                        stream.feed(data)
                    self._request_refresh()
                elif not session.is_alive():
                    # No data and the child has exited: the session is over.
                    # An idle interactive agent is still alive, so we key solely
                    # off is_alive() and never time out on silence.
                    break

                time.sleep(0.02)
        except Exception as exc:
            if self._pty is session and not stop.is_set():
                self._error = f"Terminal read failed: {exc}"
        finally:
            if self._pty is session:
                self._pty_running = False
                self._request_refresh()
