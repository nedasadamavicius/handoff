from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def atomic(path: Path, data: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def child_command(argv: list[str]) -> list[str] | str:
    if os.name != "nt" or Path(argv[0]).suffix.lower() not in {".cmd", ".bat"}:
        return argv
    if any(character in '%!&|<>^"\n\r()' for arg in argv for character in arg):
        raise ValueError("Unsupported shell metacharacters in .cmd/.bat command")
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    # cmd /s removes the outer pair; all actual arguments stay quoted.
    return f'"{comspec}" /d /s /c "' + " ".join(f'"{arg}"' for arg in argv) + '"'


def main() -> int:
    request = Path(sys.argv[1])
    data = json.loads(request.read_text(encoding="utf-8"))
    status = Path(data["status_path"])
    hwnd = None
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetConsoleWindow.restype = wintypes.HWND
        kernel.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
        kernel.SetConsoleTitleW(data["label"])
        hwnd = kernel.GetConsoleWindow()
    record = {"pid": os.getpid(), "hwnd": hwnd}
    try:
        atomic(status, record)
        env = os.environ.copy()
        if "grok" in Path(str(data["argv"][0])).stem.lower():
            # psmux 3.3.8 cannot round-trip the Kitty keyboard protocol. Inside a
            # multiplexer pane Grok still pushes KKP, so Enter and other keys arrive
            # as sequences psmux drops. Force its legacy console path, which matches
            # how Claude and Codex (no KKP) already work in these windows.
            env["GROK_FORCE_LEGACY_CONSOLE"] = "1"
        child = subprocess.Popen(child_command(data["argv"]), cwd=data["workspace"], env=env)
        # The agent owns Ctrl+C. Keep its supervising helper alive while the
        # native CLI handles cancellation in the shared external console.
        signal.signal(signal.SIGINT, lambda *_: None)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda *_: None)
        record["child_pid"] = child.pid
        atomic(status, record)
        code = child.wait()
        atomic(status, {**record, "exit_code": code})
        return code
    except Exception as exc:
        atomic(status, {**record, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
