from __future__ import annotations

import ctypes
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from handoff.session_runner import without_mux_markers


IS_WINDOWS = sys.platform == "win32"
LIVE_STATES = {"starting", "running"}
MUX_PROGRAM = "psmux" if IS_WINDOWS else "tmux"


def parse_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return list(command)
    parts = shlex.split(command, posix=False)
    return [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in parts]


def validate_shim(argv: list[str]) -> None:
    if Path(argv[0]).suffix.lower() in {".cmd", ".bat"}:
        if any(character in '%!&|<>^"\n\r()' for arg in argv for character in arg):
            raise ValueError(".cmd/.bat commands cannot contain shell metacharacters; configure the native executable instead.")


class WindowsProcessHandle:
    """Keep process identity alive until bookkeeping releases the handle."""

    def __init__(self, pid: int) -> None:
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def alive(self) -> bool:
        if not self.handle:
            return False
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0x102

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class PosixProcessHandle:
    """Liveness check for a helper that the multiplexer, not Handoff, spawned."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        if not self.alive():
            raise ProcessLookupError(pid)

    def alive(self) -> bool:
        if not self.pid:
            return False
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def close(self) -> None:
        self.pid = None


def hidden_run_kwargs() -> dict:
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def uses_console_backend(name: str, argv: list[str]) -> bool:
    """Grok on Windows gets its own console. Every other tool stays in the multiplexer."""
    if not IS_WINDOWS:
        return False
    if name.strip().lower() == "grok":
        return True
    return Path(argv[0]).stem.lower() == "grok"


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    class_name: str
    visible: bool
    area: int
    owner: int


def _user32():
    dll = getattr(_user32, "dll", None)
    if dll is not None:
        return dll
    from ctypes import wintypes

    dll = ctypes.WinDLL("user32", use_last_error=True)
    dll.IsWindow.argtypes = [wintypes.HWND]
    dll.IsWindow.restype = wintypes.BOOL
    dll.IsWindowVisible.argtypes = [wintypes.HWND]
    dll.IsWindowVisible.restype = wintypes.BOOL
    dll.IsIconic.argtypes = [wintypes.HWND]
    dll.IsIconic.restype = wintypes.BOOL
    dll.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    dll.GetAncestor.restype = wintypes.HWND
    dll.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    dll.GetWindow.restype = wintypes.HWND
    dll.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    dll.GetClassNameW.restype = ctypes.c_int
    dll.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    dll.GetWindowRect.restype = wintypes.BOOL
    dll.GetForegroundWindow.restype = wintypes.HWND
    dll.SetForegroundWindow.argtypes = [wintypes.HWND]
    dll.SetForegroundWindow.restype = wintypes.BOOL
    dll.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    dll.ShowWindow.restype = wintypes.BOOL
    dll.BringWindowToTop.argtypes = [wintypes.HWND]
    dll.BringWindowToTop.restype = wintypes.BOOL
    dll.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    dll.GetWindowThreadProcessId.restype = wintypes.DWORD
    dll.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    dll.AttachThreadInput.restype = wintypes.BOOL
    _user32.dll = dll
    return dll


def _kernel32():
    dll = getattr(_kernel32, "dll", None)
    if dll is not None:
        return dll
    from ctypes import wintypes

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.dll = dll
    return dll


def _owner_hwnd(user32, hwnd: int) -> int:
    # GA_ROOTOWNER walks the owner chain. Windows Terminal owns the
    # pseudoconsole message window from its CASCADIA_HOSTING_WINDOW_CLASS window.
    root = int(user32.GetAncestor(hwnd, 3) or 0)
    if root and root != hwnd:
        return root
    owned = int(user32.GetWindow(hwnd, 4) or 0)
    if owned and owned != hwnd:
        return owned
    return 0


def describe_window(hwnd: int) -> WindowInfo | None:
    if not IS_WINDOWS or not hwnd:
        return None
    user32 = _user32()
    if not user32.IsWindow(hwnd):
        return None
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, 256)
    rect = _Rect()
    area = 0
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
    return WindowInfo(
        int(hwnd),
        name.value,
        bool(user32.IsWindowVisible(hwnd)),
        area,
        _owner_hwnd(user32, int(hwnd)),
    )


def _focusable(info: WindowInfo) -> bool:
    # PseudoConsoleWindow is a zero-size message window. IsWindowVisible can
    # still be true, so class and area both have to pass.
    if info.class_name == "PseudoConsoleWindow":
        return False
    return bool(info.visible and info.area > 0)


def choose_console_focus(console_hwnd: int, lookup=None) -> int:
    """Return the visible terminal window for a helper-reported console HWND.

    Classic conhost reports ConsoleWindowClass, which is the window to focus.
    Windows Terminal reports a PseudoConsoleWindow; the visible window is its owner.
    """
    if lookup is None:
        lookup = describe_window
    info = lookup(int(console_hwnd))
    if info is None:
        raise RuntimeError("Console window is no longer available")
    if _focusable(info):
        return info.hwnd
    if info.owner:
        owner = lookup(int(info.owner))
        if owner is not None and _focusable(owner):
            return owner.hwnd
    raise RuntimeError("Could not find a visible terminal window for this console.")


def _foreground_is(user32, hwnd: int) -> bool:
    foreground = int(user32.GetForegroundWindow() or 0)
    if foreground == hwnd:
        return True
    if not foreground:
        return False
    return int(user32.GetAncestor(foreground, 3) or 0) == hwnd


def focus_window(hwnd: int) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Console focus is only available on Windows")
    from ctypes import wintypes

    user32 = _user32()
    kernel = _kernel32()
    target = int(hwnd)
    if user32.IsIconic(target):
        user32.ShowWindow(target, 9)
    current = int(kernel.GetCurrentThreadId())
    foreground = int(user32.GetForegroundWindow() or 0)
    attached: list[int] = []
    for window in (foreground, target):
        if not window:
            continue
        thread = int(user32.GetWindowThreadProcessId(window, ctypes.byref(wintypes.DWORD())))
        if thread and thread != current and thread not in attached:
            if user32.AttachThreadInput(current, thread, True):
                attached.append(thread)
    try:
        user32.BringWindowToTop(target)
        user32.SetForegroundWindow(target)
        if not _foreground_is(user32, target):
            raise RuntimeError("Could not focus the console window")
    finally:
        for thread in attached:
            user32.AttachThreadInput(current, thread, False)


def current_mux_session(mux: str) -> str:
    """Session this terminal is attached to. Handoff itself stays a window there."""
    named = os.environ.get("PSMUX_SESSION")
    if named:
        return named
    if not os.environ.get("TMUX"):
        raise RuntimeError(
            f"Handoff is not inside {MUX_PROGRAM}. Start it from a {MUX_PROGRAM} session "
            "so this repository's agents stay in this terminal."
        )
    found = subprocess.run(
        [mux, "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True, timeout=5, **hidden_run_kwargs(),
    )
    name = found.stdout.strip()
    if found.returncode or not name:
        detail = (found.stderr or found.stdout or "could not read the current session").strip()
        raise RuntimeError(detail)
    return name


@dataclass
class ExternalSession:
    name: str
    command: list[str]
    workspace: Path
    window_name: str | None = None
    ident: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "starting"
    pid: int | None = None
    child_pid: int | None = None
    exit_code: int | None = None
    error: str | None = None
    hwnd: int | None = None
    process: Any = field(default=None, repr=False)
    handle: Any = field(default=None, repr=False)
    terminal: str | None = None
    backend: str = "mux"
    mux_session: str | None = None
    window_id: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def label(self) -> str:
        return self.window_name or self.name


class SessionManager:
    STARTUP_TIMEOUT = 15.0

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.directory = self.workspace / ".handoff" / "external-sessions"
        self.sessions: list[ExternalSession] = []
        self._lock = threading.RLock()
        self._closed = False

    def launch(self, name: str, command: str | list[str]) -> ExternalSession:
        with self._lock:
            if self._closed:
                raise RuntimeError("Session manager is closed")
            argv = parse_command(command)
            if not argv or not argv[0]:
                raise ValueError("Tool command is empty")
            candidate = self.workspace / argv[0]
            executable = shutil.which(argv[0]) or (str(candidate.resolve()) if candidate.is_file() else None)
            if not executable:
                raise FileNotFoundError(f"Could not find executable: {argv[0]}")
            argv[0] = executable
            validate_shim(argv)
            self.directory.mkdir(parents=True, exist_ok=True)
            backend_name = "console" if uses_console_backend(name, argv) else "mux"
            mux = None
            if backend_name == "mux":
                mux = shutil.which(MUX_PROGRAM)
                if not mux:
                    raise FileNotFoundError(
                        f"Could not find {MUX_PROGRAM} on PATH. Agent sessions run as multiplexer windows."
                    )
            session = ExternalSession(
                name, argv, self.workspace, window_name=self._window_name(name), backend=backend_name,
            )
            request = self.directory / f"{session.ident}.json"
            request.write_text(json.dumps({
                "argv": argv, "workspace": str(self.workspace),
                "status_path": str(self._status_path(session)), "label": session.label,
                "backend": backend_name,
            }), encoding="utf-8")
            helper = [sys.executable, str(Path(__file__).with_name("session_runner.py")), str(request)]
            try:
                if backend_name == "console":
                    self._start_console(session, helper)
                else:
                    self._start_mux(session, mux, helper)
            except Exception as exc:
                session.state, session.error = "error", str(exc)
                self.sessions.append(session)
                raise
            self.sessions.append(session)
            return session

    def _start_console(self, session: ExternalSession, helper: list[str]) -> None:
        """Start the helper in a new console, outside the current multiplexer session."""
        env = without_mux_markers(dict(os.environ))
        # Leave standard handles unset. Python then omits STARTF_USESTDHANDLES,
        # and the new console receives the keyboard.
        session.process = subprocess.Popen(
            helper,
            cwd=str(self.workspace),
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        # Popen.pid is the Windows venv launcher. It stays alive and starts the
        # helper, whose own pid and console HWND arrive in the status file.

    def _start_mux(self, session: ExternalSession, mux: str, helper: list[str]) -> None:
        session.terminal = mux
        session.mux_session = current_mux_session(mux)
        created = subprocess.run(
            self._agent_window_command(mux, session, helper),
            capture_output=True, text=True, timeout=15, **hidden_run_kwargs(),
        )
        if created.returncode:
            detail = (created.stderr or created.stdout or "multiplexer rejected the window").strip()
            raise RuntimeError(detail)
        session.window_id = created.stdout.strip() or session.label

    def _window_name(self, name: str) -> str:
        repository = self.workspace.name or "workspace"
        number = sum(session.name == name for session in self.sessions) + 1
        agent = name.title() if number == 1 else f"{name.title()} {number}"
        return f"{agent}: {repository}"

    def _agent_window_command(self, mux: str, session: ExternalSession, helper: list[str]) -> list[str]:
        """Create an agent window in the session that already contains Handoff."""
        window = ["-d", "-P", "-F", "#{window_id}", "-c", str(self.workspace), "-n", session.label, "--", *helper]
        return [mux, "new-window", *window[:4], "-t", session.mux_session, *window[4:]]

    def rename_handoff_window(self) -> None:
        """Give the current workspace window a short, recognizable name."""
        mux = shutil.which(MUX_PROGRAM)
        if not mux or not (os.environ.get("PSMUX_SESSION") or os.environ.get("TMUX")):
            return
        renamed = subprocess.run(
            [mux, "rename-window", f"HO: {self.workspace.name or 'workspace'}"],
            capture_output=True, text=True, timeout=5, **hidden_run_kwargs(),
        )
        if renamed.returncode:
            detail = (renamed.stderr or renamed.stdout or "Could not rename the Handoff window").strip()
            raise RuntimeError(detail)

    def _status_path(self, session: ExternalSession) -> Path:
        return self.directory / f"{session.ident}.status.json"

    @staticmethod
    def _finish(session: ExternalSession, error: str | None = None) -> None:
        session.state = "error" if error else "exited"
        session.error = error
        if session.handle is not None:
            session.handle.close()
            session.handle = None

    def refresh(self) -> None:
        with self._lock:
            if self._closed:
                return
            for session in self.sessions:
                if session.state not in LIVE_STATES:
                    continue
                data: dict = {}
                try:
                    decoded = json.loads(self._status_path(session).read_text(encoding="utf-8"))
                    if isinstance(decoded, dict):
                        data = decoded
                except (OSError, ValueError):
                    pass
                pid = data.get("pid")
                if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                    if session.pid is None:
                        session.pid = pid
                    elif session.pid != pid:
                        session.error = "Session status PID changed; ignoring invalid record"
                        data = {}
                child = data.get("child_pid")
                if isinstance(child, int) and not isinstance(child, bool) and child > 0:
                    session.child_pid = child
                hwnd = data.get("hwnd")
                if isinstance(hwnd, int) and not isinstance(hwnd, bool) and hwnd > 0:
                    session.hwnd = hwnd
                if data.get("error"):
                    self._finish(session, str(data["error"]))
                    continue
                if isinstance(data.get("exit_code"), int):
                    session.exit_code = data["exit_code"]
                    self._finish(session)
                    continue
                if session.pid and session.handle is None:
                    try:
                        session.handle = WindowsProcessHandle(session.pid) if IS_WINDOWS else PosixProcessHandle(session.pid)
                    except OSError as exc:
                        # ERROR_INVALID_PARAMETER means the process no longer exists.
                        if getattr(exc, "winerror", None) == 87:
                            self._finish(session)
                        else:
                            session.error = f"Cannot track session process: {exc}"
                        continue
                if session.handle is not None:
                    try:
                        alive = session.handle.alive()
                    except OSError as exc:
                        session.error = f"Cannot query session process: {exc}"
                        continue
                    if not alive:
                        self._finish(session)
                    else:
                        session.state = "running"
                        session.error = None
                    continue
                launcher_code = session.process.poll() if session.process else None
                if launcher_code is not None and (session.terminal is None or launcher_code != 0):
                    kind = "Console helper" if session.backend == "console" else "Terminal launcher"
                    self._finish(session, f"{kind} exited before startup (code {launcher_code})")
                elif time.monotonic() - session.started_at > self.STARTUP_TIMEOUT:
                    detail = "Session did not report startup within 15 seconds."
                    if session.backend != "console":
                        detail += " Check the multiplexer."
                    self._finish(session, detail)

    def _live_handle(self, session: ExternalSession) -> None:
        if self._closed or session not in self.sessions:
            raise RuntimeError("Session is no longer tracked")
        if session.state not in LIVE_STATES:
            raise RuntimeError("Session has already exited")
        if session.handle is None or session.pid is None:
            raise RuntimeError("Session process is not available yet; it cannot be controlled safely")
        if not session.handle.alive():
            self._finish(session)
            raise RuntimeError("Session has already exited")

    def open(self, session: ExternalSession) -> None:
        with self._lock:
            self.refresh()
            self._live_handle(session)
            if session.backend == "console":
                self._open_console(session)
                return
            if not session.terminal or not session.mux_session:
                raise RuntimeError("Session has no multiplexer window")
            target = session.window_id if session.window_id and session.window_id.startswith("@") else f"{session.mux_session}:{session.label}"
            selected = subprocess.run(
                [session.terminal, "switch-client", "-t", target],
                capture_output=True, text=True, timeout=5, **hidden_run_kwargs(),
            )
            if selected.returncode:
                detail = (selected.stderr or selected.stdout or "Could not select the multiplexer window").strip()
                raise RuntimeError(detail)

    def _open_console(self, session: ExternalSession) -> None:
        if not session.hwnd:
            raise RuntimeError("Console window is not available yet")
        focus_window(choose_console_focus(session.hwnd))

    def _force_stop(self, pid: int) -> subprocess.CompletedProcess:
        if IS_WINDOWS:
            return subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        return subprocess.run(
            ["kill", "-KILL", str(pid)],
            capture_output=True, text=True, timeout=10,
        )

    def stop(self, session: ExternalSession) -> None:
        with self._lock:
            self.refresh()
            if session.state not in LIVE_STATES:
                raise RuntimeError("Session has already exited")
            # Kill the console launcher so its helper, agent, and conhost all stop.
            launcher_alive = (
                session.backend == "console"
                and session.process is not None
                and session.process.poll() is None
            )
            if launcher_alive:
                target = session.process.pid
            else:
                self._live_handle(session)
                target = session.pid
            if not IS_WINDOWS and session.child_pid and session.child_pid != session.pid:
                self._force_stop(session.child_pid)
            result = self._force_stop(target)
            if result.returncode:
                if session.handle is not None and not session.handle.alive():
                    self._finish(session)
                    return
                if session.process is not None and session.process.poll() is not None:
                    self._finish(session)
                    return
                raise RuntimeError((result.stderr or result.stdout or "Could not stop session").strip())
            self._finish(session)

    def remove(self, session: ExternalSession) -> None:
        with self._lock:
            self.refresh()
            if session.state in LIVE_STATES:
                raise RuntimeError("Stop the session before removing it")
            self.sessions.remove(session)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            for session in self.sessions:
                if session.handle is not None:
                    session.handle.close()
                    session.handle = None
