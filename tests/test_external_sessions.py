from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import handoff.external_sessions as backend
from handoff.external_sessions import (
    ExternalSession,
    SessionManager,
    WindowInfo,
    WindowsProcessHandle,
    choose_console_focus,
    parse_command,
)
from handoff.session_runner import without_mux_markers


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PSMUX_SESSION", "repo-a")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(backend, "IS_WINDOWS", True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(backend.shutil, "which", lambda name: "psmux.exe" if name == "psmux" else str(tmp_path / (name + ".exe")))
    handle = Mock()
    handle.alive.return_value = True
    handles = Mock(return_value=handle)
    monkeypatch.setattr(backend, "WindowsProcessHandle", handles)

    def fake_run(args, **kwargs):
        command = args[1] if len(args) > 1 else ""
        if command == "new-window":
            return subprocess.CompletedProcess(args, 0, "@7\n", "")
        if command == "list-clients":
            return subprocess.CompletedProcess(args, 0, "alacritty\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    run = Mock(side_effect=fake_run)
    monkeypatch.setattr(backend.subprocess, "run", run)

    def fake_popen(args, **kwargs):
        process = Mock()
        process.pid = 4242
        process.poll.return_value = None
        return process

    monkeypatch.setattr(backend.subprocess, "Popen", Mock(side_effect=fake_popen))
    return SessionManager(tmp_path), handles, handle, run


def report(manager, session, **data):
    manager._status_path(session).write_text(json.dumps(data), encoding="utf-8")


def running(environment):
    manager, handles, handle, run = environment
    session = manager.launch("agent", ["agent"])
    report(manager, session, pid=12345, hwnd=456)
    manager.refresh()
    assert session.state == "running"
    return session


def mux_calls(run, command):
    return [call.args[0] for call in run.call_args_list if len(call.args[0]) > 1 and call.args[0][1] == command]


def new_window_calls(run):
    return mux_calls(run, "new-window")


def test_two_launches_have_distinct_windows_and_no_agent_output_pipe(environment):
    manager, _, _, run = environment
    first = manager.launch("agent", ["agent"])
    second = manager.launch("agent", ["agent"])
    assert first.ident != second.ident
    assert len(manager.sessions) == 2
    windows = new_window_calls(run)
    assert not mux_calls(run, "new-session")
    assert len(windows) == 2
    assert first.mux_session == second.mux_session == "repo-a"
    assert windows[0][1:5] == ["new-window", "-d", "-P", "-F"]
    assert windows[0][windows[0].index("-t") + 1] == "repo-a"
    assert windows[0][windows[0].index("-n") + 1] == f"Agent: {manager.workspace.name}"
    assert windows[1][windows[1].index("-n") + 1] == f"Agent 2: {manager.workspace.name}"
    assert first.window_id == "@7"
    request = json.loads((manager.directory / f"{first.ident}.json").read_text())
    assert request["workspace"] == str(manager.workspace)
    assert "session_runner.py" in windows[0][-2]


def test_missing_status_times_out_without_treating_mux_as_the_agent(environment):
    manager = environment[0]
    session = manager.launch("agent", "agent")
    manager.refresh()
    assert session.state == "starting"
    session.started_at -= 16
    manager.refresh()
    assert session.state == "error"
    assert "startup" in session.error


def test_workspaces_add_agent_windows_to_their_attached_sessions(environment, monkeypatch, tmp_path):
    first_manager, _, _, run = environment
    first = first_manager.launch("agent", "agent")
    monkeypatch.setenv("PSMUX_SESSION", "repo-b")
    second_manager = SessionManager(tmp_path / "repo-b")
    second = second_manager.launch("agent", "agent")

    windows = new_window_calls(run)
    assert first.mux_session == "repo-a"
    assert second.mux_session == "repo-b"
    assert [args[args.index("-t") + 1] for args in windows] == ["repo-a", "repo-b"]
    assert [args[args.index("-c") + 1] for args in windows] == [
        str(first_manager.workspace), str(second_manager.workspace),
    ]


def test_failed_new_window_is_reported(environment):
    manager, _, _, run = environment

    def reject_window(args, **kwargs):
        if args[1] == "new-window":
            return subprocess.CompletedProcess(args, 1, "", "pane failed")
        return subprocess.CompletedProcess(args, 0, "", "")

    run.side_effect = reject_window
    with pytest.raises(RuntimeError, match="pane failed"):
        manager.launch("agent", "agent")
    assert manager.sessions[0].state == "error"


def test_process_handle_detects_manual_window_close(environment):
    session = running(environment)
    manager, handles, handle, _ = environment
    handles.assert_called_once_with(12345)
    handle.alive.return_value = False
    manager.refresh()
    assert session.state == "exited"
    assert session.exit_code is None
    handle.close.assert_called_once()


def test_final_exit_status_releases_handle(environment):
    session = running(environment)
    manager, _, handle, _ = environment
    report(manager, session, pid=session.pid, exit_code=7)
    manager.refresh()
    assert (session.state, session.exit_code) == ("exited", 7)
    handle.close.assert_called_once()


def test_stop_only_selected_helper(environment):
    session = running(environment)
    manager, _, handle, run = environment
    other = manager.launch("agent", "agent")
    manager.stop(session)
    args, kwargs = run.call_args
    assert args[0] == ["taskkill.exe", "/PID", "12345", "/T", "/F"]
    assert kwargs["timeout"] == 10
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert session.state == "exited"
    assert other.state == "starting"
    handle.close.assert_called_once()


def test_failed_stop_preserves_running_state(environment):
    session = running(environment)
    manager, _, handle, run = environment

    def deny_kill(args, **kwargs):
        if args[0] == "taskkill.exe":
            return subprocess.CompletedProcess(args, 1, "", "access denied")
        return subprocess.CompletedProcess(args, 0, "", "")

    run.side_effect = deny_kill
    with pytest.raises(RuntimeError, match="access denied"):
        manager.stop(session)
    assert session.state == "running"
    handle.close.assert_not_called()


def test_exited_or_unverified_pid_is_never_killed(environment):
    session = running(environment)
    manager, _, handle, run = environment
    handle.alive.return_value = False
    with pytest.raises(RuntimeError, match="exited"):
        manager.stop(session)
    other = manager.launch("agent", "agent")
    with pytest.raises(RuntimeError, match="safely"):
        manager.stop(other)
    assert not any(call.args[0][0] == "taskkill.exe" for call in run.call_args_list)


def test_open_selects_existing_mux_window(environment, monkeypatch):
    session = running(environment)
    manager, _, _, run = environment
    monkeypatch.setattr(backend.shutil, "which", lambda _: None)
    manager.open(session)
    assert run.call_args.args[0][1:] == ["switch-client", "-t", "@7"]


def console_windows():
    return {
        100: WindowInfo(100, "PseudoConsoleWindow", True, 0, 200),
        200: WindowInfo(200, "CASCADIA_HOSTING_WINDOW_CLASS", True, 716915, 0),
        300: WindowInfo(300, "ConsoleWindowClass", True, 5000, 0),
    }


def test_grok_on_windows_opens_a_console_without_the_multiplexer(environment, monkeypatch):
    manager, _, _, run = environment
    monkeypatch.setenv("TMUX", "pipe")
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setenv("PSMUX_SESSION", "main")
    monkeypatch.setenv("PSMUX_CONFIG_FILE", "shared")
    monkeypatch.setenv("TMUX_TMPDIR", "keep")
    session = manager.launch("grok", "grok")
    popen = backend.subprocess.Popen
    args, kwargs = popen.call_args
    assert session.backend == "console"
    assert session.mux_session is None
    assert session.terminal is None
    assert session.pid is None
    assert session.process.pid == 4242
    assert not new_window_calls(run)
    assert kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    assert kwargs["cwd"] == str(manager.workspace)
    assert "stdin" not in kwargs
    assert args[0][-2].endswith("session_runner.py")
    env = kwargs["env"]
    assert "TMUX" not in {key.upper() for key in env}
    assert "TMUX_PANE" not in {key.upper() for key in env}
    assert not any(key.upper().startswith("PSMUX_") for key in env)
    assert env["TMUX_TMPDIR"] == "keep"
    assert os.environ["TMUX"] == "pipe"
    assert os.environ["PSMUX_SESSION"] == "main"
    request = json.loads((manager.directory / f"{session.ident}.json").read_text())
    assert request["backend"] == "console"
    manager.refresh()
    assert session.state == "starting"
    with pytest.raises(RuntimeError, match="not available yet"):
        manager.open(session)
    report(manager, session, pid=4242, hwnd=100, child_pid=99)
    manager.refresh()
    assert session.pid == 4242
    assert session.state == "running"
    assert session.hwnd == 100
    focused = []
    monkeypatch.setattr(backend, "describe_window", lambda hwnd: console_windows().get(hwnd))
    monkeypatch.setattr(backend, "focus_window", focused.append)
    manager.open(session)
    assert focused == [200]
    assert not mux_calls(run, "switch-client")


def test_grok_console_does_not_require_psmux(environment, monkeypatch):
    monkeypatch.delenv("PSMUX_SESSION", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(backend.shutil, "which", lambda name: None if name == "psmux" else name)
    manager = environment[0]
    session = manager.launch("assistant", [r"C:\tools\grok.exe"])
    assert session.backend == "console"
    assert session.mux_session is None
    with pytest.raises(FileNotFoundError, match="psmux"):
        manager.launch("claude", "claude")


def test_named_grok_uses_console_and_claude_stays_in_psmux(environment):
    manager, _, _, run = environment
    claude = manager.launch("claude", "claude")
    grok = manager.launch("grok", "claude")
    assert claude.backend == "mux"
    assert claude.mux_session == "repo-a"
    assert grok.backend == "console"
    assert len(new_window_calls(run)) == 1
    assert backend.subprocess.Popen.call_count == 1


def test_console_open_rejects_a_hidden_host(environment, monkeypatch):
    manager = environment[0]
    session = manager.launch("grok", "grok")
    report(manager, session, pid=4242, hwnd=100)
    manager.refresh()
    hidden = {
        100: WindowInfo(100, "PseudoConsoleWindow", True, 0, 200),
        200: WindowInfo(200, "CASCADIA_HOSTING_WINDOW_CLASS", False, 1000, 0),
    }
    monkeypatch.setattr(backend, "describe_window", lambda hwnd: hidden.get(hwnd))
    monkeypatch.setattr(backend, "focus_window", lambda hwnd: (_ for _ in ()).throw(AssertionError(hwnd)))
    with pytest.raises(RuntimeError, match="visible terminal"):
        manager.open(session)
    assert session.state == "running"


def test_console_status_pid_can_differ_from_the_launcher(environment, monkeypatch):
    manager, handles, _, run = environment
    session = manager.launch("grok", "grok")
    assert session.pid is None
    report(manager, session, pid=5555, hwnd=100, child_pid=99)
    manager.refresh()
    assert session.pid == 5555
    assert session.hwnd == 100
    assert session.state == "running"
    handles.assert_called_with(5555)
    focused = []
    monkeypatch.setattr(backend, "describe_window", lambda hwnd: console_windows().get(hwnd))
    monkeypatch.setattr(backend, "focus_window", focused.append)
    manager.open(session)
    assert focused == [200]
    manager.stop(session)
    assert run.call_args.args[0] == ["taskkill.exe", "/PID", "4242", "/T", "/F"]
    assert session.state == "exited"


def test_console_stop_remove_and_shutdown(environment):
    manager, _, handle, run = environment
    session = manager.launch("grok", "grok")
    report(manager, session, pid=4242, hwnd=300, exit_code=None)
    manager.refresh()
    assert session.state == "running"
    manager.stop(session)
    assert run.call_args.args[0] == ["taskkill.exe", "/PID", "4242", "/T", "/F"]
    assert session.state == "exited"
    handle.close.assert_called_once()
    manager.remove(session)
    assert session not in manager.sessions
    other = manager.launch("grok", "grok")
    report(manager, other, pid=4242, hwnd=300)
    manager.refresh()
    launches = len(run.call_args_list)
    manager.shutdown()
    assert len(run.call_args_list) == launches
    assert other.state == "running"


def test_console_launch_failure_is_tracked(environment):
    manager = environment[0]
    backend.subprocess.Popen.side_effect = OSError("console failed")
    with pytest.raises(OSError, match="console failed"):
        manager.launch("grok", "grok")
    assert manager.sessions[0].state == "error"
    assert manager.sessions[0].error == "console failed"


def test_choose_console_focus_prefers_a_visible_host():
    windows = console_windows()
    assert choose_console_focus(300, windows.get) == 300
    assert choose_console_focus(100, windows.get) == 200
    broken = {
        100: WindowInfo(100, "PseudoConsoleWindow", True, 50, 200),
        200: WindowInfo(200, "PseudoConsoleWindow", True, 50, 0),
    }
    with pytest.raises(RuntimeError, match="visible terminal"):
        choose_console_focus(100, broken.get)
    with pytest.raises(RuntimeError, match="no longer available"):
        choose_console_focus(1, lambda hwnd: None)


def test_without_mux_markers_keeps_unrelated_variables():
    source = {
        "PATH": "C:\\bin",
        "TMUX": "pipe",
        "TMUX_PANE": "%1",
        "TMUX_TMPDIR": "keep",
        "PSMUX_SESSION": "main",
        "psmux_config_file": "shared",
        "TERM": "xterm-256color",
    }
    cleaned = without_mux_markers(source)
    assert cleaned == {"PATH": "C:\\bin", "TMUX_TMPDIR": "keep", "TERM": "xterm-256color"}
    assert source["TMUX"] == "pipe"


def test_describe_window_rejects_a_missing_hwnd():
    assert backend.describe_window(0) is None


def test_launch_outside_multiplexer_is_refused(environment, monkeypatch):
    monkeypatch.delenv("PSMUX_SESSION", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    manager = environment[0]
    with pytest.raises(RuntimeError, match="not inside psmux"):
        manager.launch("agent", "agent")


def test_tmux_environment_names_the_current_session(environment, monkeypatch):
    monkeypatch.delenv("PSMUX_SESSION", raising=False)
    monkeypatch.setenv("TMUX", r"\\.\pipe\psmux,1,0")
    manager, _, _, run = environment

    def name_session(args, **kwargs):
        if args[1] == "display-message":
            return subprocess.CompletedProcess(args, 0, "repo-b\n", "")
        if args[1] == "new-window":
            return subprocess.CompletedProcess(args, 0, "@1\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    run.side_effect = name_session
    session = manager.launch("agent", "agent")
    created = mux_calls(run, "new-window")
    assert session.mux_session == "repo-b"
    assert created[0][created[0].index("-t") + 1] == session.mux_session


def test_handoff_window_gets_short_repository_name(environment):
    manager, _, _, run = environment

    manager.rename_handoff_window()

    assert mux_calls(run, "rename-window") == [["psmux.exe", "rename-window", f"HO: {manager.workspace.name}"]]


def test_remove_live_refused_and_shutdown_does_not_stop(environment):
    session = running(environment)
    manager, _, handle, run = environment
    with pytest.raises(RuntimeError, match="Stop"):
        manager.remove(session)
    launches = len(run.call_args_list)
    manager.shutdown()
    handle.close.assert_called_once()
    assert len(run.call_args_list) == launches
    assert session.state == "running"


def test_missing_agent_and_missing_multiplexer(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "IS_WINDOWS", True)
    monkeypatch.setattr(backend.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="executable"):
        SessionManager(tmp_path).launch("agent", "missing")
    monkeypatch.setattr(backend.shutil, "which", lambda name: "agent.exe" if name == "agent" else None)
    with pytest.raises(FileNotFoundError, match="psmux"):
        SessionManager(tmp_path).launch("agent", "agent")


def test_posix_grok_stays_in_tmux(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,1,0")
    monkeypatch.delenv("PSMUX_SESSION", raising=False)
    monkeypatch.setattr(backend, "IS_WINDOWS", False)
    monkeypatch.setattr(backend, "MUX_PROGRAM", "tmux")
    monkeypatch.setattr(backend.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else "/usr/bin/grok")

    def fake_run(args, **kwargs):
        if args[1] == "display-message":
            return subprocess.CompletedProcess(args, 0, "repo-a\n", "")
        if args[1] == "new-window":
            return subprocess.CompletedProcess(args, 0, "@3\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    run = Mock(side_effect=fake_run)
    monkeypatch.setattr(backend.subprocess, "run", run)
    session = SessionManager(tmp_path).launch("grok", "grok")
    assert session.backend == "mux"
    assert session.terminal == "/usr/bin/tmux"
    assert mux_calls(run, "new-window")


def test_posix_launch_uses_tmux_and_kills_helper_not_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,1,0")
    monkeypatch.delenv("PSMUX_SESSION", raising=False)
    monkeypatch.setattr(backend, "IS_WINDOWS", False)
    monkeypatch.setattr(backend, "MUX_PROGRAM", "tmux")
    monkeypatch.setattr(backend.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else "/usr/bin/agent")
    handle = Mock()
    handle.alive.return_value = True
    monkeypatch.setattr(backend, "PosixProcessHandle", Mock(return_value=handle))

    def fake_run(args, **kwargs):
        if args[1] == "display-message":
            return subprocess.CompletedProcess(args, 0, "repo-a\n", "")
        if args[1] == "new-window":
            return subprocess.CompletedProcess(args, 0, "@3\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    run = Mock(side_effect=fake_run)
    monkeypatch.setattr(backend.subprocess, "run", run)
    manager = SessionManager(tmp_path)
    session = manager.launch("agent", "agent")
    assert session.terminal == "/usr/bin/tmux"
    assert mux_calls(run, "new-window")[0][0] == "/usr/bin/tmux"
    report(manager, session, pid=50, child_pid=51)
    manager.refresh()
    manager.stop(session)
    killed = [call.args[0] for call in run.call_args_list if call.args[0][0] == "kill"]
    assert killed == [["kill", "-KILL", "51"], ["kill", "-KILL", "50"]]
    assert session.state == "exited"


def test_parse_preserves_spaces_and_native_metacharacters():
    assert parse_command('"C:\\Program Files\\agent.exe" "hello world" a^b') == [r'C:\Program Files\agent.exe', 'hello world', 'a^b']
    assert parse_command(["agent", 'a"b', "a&b"]) == ["agent", 'a"b', "a&b"]


def test_shim_metacharacters_rejected_after_resolution(environment, monkeypatch):
    manager = environment[0]
    monkeypatch.setattr(backend.shutil, "which", lambda _: "tool.cmd")
    for argument in ["bad&arg", "bad%arg", 'bad"arg']:
        with pytest.raises(ValueError, match="metacharacters"):
            manager.launch("tool", ["tool", argument])


def invoke_runner(tmp_path, argv, backend="mux"):
    status = tmp_path / "status.json"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "argv": argv, "workspace": str(tmp_path), "status_path": str(status), "label": "test", "backend": backend,
    }))
    result = subprocess.run(
        [sys.executable, "-m", "handoff.session_runner", str(request)],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result, json.loads(status.read_text())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console helper")
def test_runner_records_exit_and_launch_error(tmp_path):
    result, data = invoke_runner(tmp_path, [sys.executable, "-c", "raise SystemExit(3)"])
    assert result.returncode == data["exit_code"] == 3
    assert data["pid"] != data["child_pid"]
    result, data = invoke_runner(tmp_path, [str(tmp_path / "missing.exe")])
    assert result.returncode == 1
    assert data["error"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command shim")
def test_runner_console_drops_mux_markers_and_legacy_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX", "pipe")
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setenv("PSMUX_SESSION", "main")
    monkeypatch.setenv("GROK_FORCE_LEGACY_CONSOLE", "1")
    shim = tmp_path / "grok.cmd"
    shim.write_text(
        "@echo off\n"
        "echo TMUX=[%TMUX%]\n"
        "echo PANE=[%TMUX_PANE%]\n"
        "echo PSMUX=[%PSMUX_SESSION%]\n"
        "echo LEGACY=[%GROK_FORCE_LEGACY_CONSOLE%]\n"
        "exit /b 0\n"
    )
    result, data = invoke_runner(tmp_path, [str(shim)], backend="console")
    text = result.stdout.decode("utf-8", errors="replace")
    assert result.returncode == data["exit_code"] == 0
    assert "TMUX=[]" in text
    assert "PANE=[]" in text
    assert "PSMUX=[]" in text
    assert "LEGACY=[]" in text
    assert os.environ["TMUX"] == "pipe"
    result, data = invoke_runner(tmp_path, [str(shim)], backend="mux")
    text = result.stdout.decode("utf-8", errors="replace")
    assert result.returncode == data["exit_code"] == 0
    assert "TMUX=[pipe]" in text
    assert "PSMUX=[main]" in text
    assert "LEGACY=[1]" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command shim")
def test_runner_cmd_shim_with_spaced_path_and_argument(tmp_path):
    shim = tmp_path / "tool with spaces.cmd"
    shim.write_text('@echo off\necho %~1\nexit /b 4\n')
    result, data = invoke_runner(tmp_path, [str(shim), "hello world"])
    assert result.returncode == data["exit_code"] == 4
    assert b"hello world" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process handle")
def test_real_process_handle_detects_exit_without_window():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"], creationflags=subprocess.CREATE_NO_WINDOW)
    handle = WindowsProcessHandle(process.pid)
    try:
        assert handle.alive()
        process.terminate()
        process.wait(timeout=5)
        assert not handle.alive()
    finally:
        handle.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
