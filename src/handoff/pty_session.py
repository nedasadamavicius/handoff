from __future__ import annotations

import sys
from typing import Any


class PtyUnavailable(RuntimeError):
    """The platform PTY backend could not be imported/started."""


class PtySession:
    """Cross-platform PTY wrapper supporting Windows (winpty) and POSIX (ptyprocess)."""

    def __init__(self) -> None:
        """Initialize a PTY session (not yet spawned)."""
        self._proc: Any = None

    def spawn(
        self,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        rows: int = 24,
        cols: int = 80,
    ) -> None:
        """Spawn a child process in a PTY.

        Args:
            argv: Command and arguments to execute.
            cwd: Working directory for the child (optional).
            env: Environment variables (optional).
            rows: Terminal rows.
            cols: Terminal columns.

        Raises:
            PtyUnavailable: If the PTY backend cannot be imported.
        """
        if sys.platform == "win32":
            try:
                from winpty import PtyProcess
            except ImportError:
                raise PtyUnavailable(
                    "PtyProcess not available. Install pywinpty: pip install pywinpty"
                )
        else:
            try:
                from ptyprocess import PtyProcess
            except ImportError:
                raise PtyUnavailable(
                    "PtyProcess not available. Install ptyprocess: pip install ptyprocess"
                )

        self._proc = PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(rows, cols)
        )

    def read(self) -> bytes:
        """Read available output from the PTY.

        Returns:
            Output as bytes. Returns b"" if the process is not spawned,
            closed, or no data is available.
        """
        if self._proc is None:
            return b""

        try:
            data = self._proc.read()
            # winpty returns str; ptyprocess returns bytes
            if isinstance(data, str):
                return data.encode("utf-8", errors="replace")
            return data
        except (EOFError, OSError):
            return b""

    def write(self, data: bytes) -> None:
        """Write data to the PTY.

        Args:
            data: Bytes to write.
        """
        if self._proc is None:
            return

        try:
            # winpty expects str; ptyprocess expects bytes
            if sys.platform == "win32":
                self._proc.write(data.decode("utf-8", errors="replace"))
            else:
                self._proc.write(data)
        except (OSError, ValueError):
            pass

    def resize(self, rows: int, cols: int) -> None:
        """Resize the terminal.

        Args:
            rows: New row count.
            cols: New column count.
        """
        if self._proc is None:
            return

        try:
            self._proc.setwinsize(rows, cols)
        except (OSError, ValueError):
            pass

    def is_alive(self) -> bool:
        """Check if the child process is still alive.

        Returns:
            True if the process is running, False otherwise.
        """
        if self._proc is None:
            return False

        try:
            return self._proc.isalive()
        except (OSError, ValueError):
            return False

    def terminate(self) -> None:
        """Force-terminate the child process.

        This is idempotent and never raises.
        """
        if self._proc is None:
            return

        try:
            self._proc.terminate(force=True)
        except (OSError, ValueError, AttributeError):
            pass

    def wait(self) -> int | None:
        """Wait for the child process to exit and return its exit status.

        Returns:
            Exit status as an int, or None if unknown.
        """
        if self._proc is None:
            return None

        try:
            return self._proc.wait()
        except (OSError, ValueError):
            return None
