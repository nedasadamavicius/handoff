from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable


class ACPError(RuntimeError):
    """The ACP peer, transport, or protocol returned an error."""


Callback = Callable[[dict], Awaitable[object]]
ErrorCallback = Callable[[Exception], Awaitable[object]]


class ACPClient:
    def __init__(self, command: list[str], cwd: Path, on_update: Callback | None = None,
                 on_permission: Callback | None = None,
                 on_error: ErrorCallback | None = None):
        self.command, self.cwd = command, Path(cwd)
        self.on_update, self.on_permission = on_update, on_permission
        self.on_error = on_error
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        self._reader_task = self._stderr_task = None
        self._pending: dict[int, asyncio.Future] = {}
        self._permissions: dict[int, asyncio.Future] = {}
        self._permission_tasks: set[asyncio.Task] = set()
        self._write_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._next_id = 1
        self._closed = False
        self._fatal: ACPError | None = None
        self.stderr = ""
        self.callback_errors: list[ACPError] = []

    async def start(self):
        if self.process is not None:
            return self
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command, cwd=str(self.cwd), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self._reader_task = asyncio.create_task(self._read_stdout())
            self._stderr_task = asyncio.create_task(self._read_stderr())
            version = await self._request("initialize", {
                "protocolVersion": 1, "clientCapabilities": {},
                "clientInfo": {"name": "handoff", "version": "0.1.0"},
            }, timeout=10)
            if version.get("protocolVersion") != 1:
                raise ACPError(f"unsupported ACP protocol version: {version.get('protocolVersion')!r}")
            result = await self._request("session/new", {
                "cwd": str(self.cwd.absolute()), "mcpServers": []}, timeout=10)
            self.session_id = result.get("sessionId")
            if not self.session_id:
                raise ACPError("session/new response did not contain sessionId")
            return self
        except BaseException:
            await self.close()
            raise

    async def prompt(self, text: str) -> dict:
        if self.process is None or self.session_id is None:
            raise ACPError("client is not started")
        if self._turn_lock.locked():
            raise ACPError("a prompt turn is already in progress")
        async with self._turn_lock:
            return await self._request("session/prompt", {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": text}],
            })

    async def cancel(self):
        if self.process is None or self.session_id is None:
            return
        for future in list(self._permissions.values()):
            if not future.done():
                future.set_result({"outcome": {"outcome": "cancelled"}})
        for task in list(self._permission_tasks):
            task.cancel()
        await self._notify("session/cancel", {"sessionId": self.session_id})

    async def close(self):
        if self._closed:
            return
        self._closed = True
        for future in list(self._pending.values()) + list(self._permissions.values()):
            if not future.done():
                future.set_exception(ACPError("client closed"))
        for task in list(self._permission_tasks):
            task.cancel()
        process = self.process
        if process is not None:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if process.stdin is not None:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (AttributeError, BrokenPipeError, ConnectionError):
                    pass
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task is not None),
            return_exceptions=True,
        )
        self.process = None

    async def _request(self, method: str, params: dict, timeout: float | None = None):
        ident = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(ident, None)

    async def _notify(self, method: str, params: dict):
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, message: dict):
        if not self.process or not self.process.stdin:
            raise ACPError("ACP process is not running")
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        async with self._write_lock:
            try:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionError) as exc:
                raise ACPError("ACP process pipe closed") from exc

    async def _read_stdout(self):
        assert self.process and self.process.stdout
        try:
            async for raw in self.process.stdout:
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError("not an object")
                    await self._dispatch(message)
                except (json.JSONDecodeError, ValueError) as exc:
                    self._fail_all(ACPError(f"malformed ACP message: {exc}"))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._fail_all(ACPError(f"ACP reader failed: {type(exc).__name__}: {exc}"))
        finally:
            if not self._closed:
                self._fail_all(self._fatal or await self._ended_error())

    async def _dispatch(self, message: dict):
        if "id" in message and ("result" in message or "error" in message):
            future = self._pending.get(message["id"])
            if future is None:
                return
            if "error" in message:
                error = message["error"]
                future.set_exception(ACPError(f"ACP error {error}"))
            else:
                future.set_result(message["result"])
            return
        method = message.get("method")
        if not method:
            return
        params = message.get("params") or {}
        if method == "session/update":
            if self.on_update:
                try:
                    await self.on_update(params)
                except Exception as exc:
                    error = ACPError(f"Could not display ACP update: {type(exc).__name__}: {exc}")
                    self.callback_errors.append(error)
                    if self.on_error:
                        try:
                            await self.on_error(error)
                        except Exception:
                            pass
        elif method in ("session/request_permission", "session/requestPermission"):
            ident = message.get("id")
            if ident is not None:
                task = asyncio.create_task(self._answer_permission(ident, params))
                self._permission_tasks.add(task)
                task.add_done_callback(self._permission_tasks.discard)
        elif "id" in message:
            await self._send({"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -32601, "message": "Method not found"}})

    async def _answer_permission(self, ident: int, params: dict):
        result = {"outcome": {"outcome": "cancelled"}}
        if self.on_permission:
            try:
                result = self._permission_result(params, await self.on_permission(params))
            except asyncio.CancelledError:
                result = {"outcome": {"outcome": "cancelled"}}
            except Exception:
                pass
        try:
            await self._send({"jsonrpc": "2.0", "id": ident, "result": result})
        except ACPError:
            pass

    def _permission_result(self, params: dict, selected: object) -> dict:
        if isinstance(selected, dict) and "outcome" in selected:
            outcome = selected["outcome"]
            if outcome == "cancelled":
                return {"outcome": {"outcome": "cancelled"}}
            option_id = selected.get("optionId")
        else:
            option_id = selected
        options = params.get("options", [])
        valid = {o.get("optionId") for o in options if isinstance(o, dict)}
        if option_id not in valid:
            return {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "selected", "optionId": option_id}}

    async def _read_stderr(self):
        assert self.process and self.process.stderr
        try:
            async for data in self.process.stderr:
                self.stderr = (self.stderr + data.decode(errors="replace"))[-8192:]
        except asyncio.CancelledError:
            return

    async def _ended_error(self) -> ACPError:
        process = self.process
        code = process.returncode if process else None
        if process and code is None:
            try:
                code = await asyncio.wait_for(process.wait(), 0.25)
            except asyncio.TimeoutError:
                pass
        if self._stderr_task and not self._stderr_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._stderr_task), 0.25)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        detail = " ".join(self.stderr.strip().splitlines())
        if len(detail) > 1000:
            detail = detail[-1000:]
        status = f" with status {code}" if code is not None else " after closing stdout"
        suffix = f": {detail}" if detail else ""
        return ACPError(f"ACP process exited{status}{suffix}")

    def _fail_all(self, error: ACPError):
        self._fatal = error
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(error)
