from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Awaitable, Callable


class ClaudeStreamError(RuntimeError):
    pass


class ClaudeStreamClient:
    def __init__(self, command: list[str], cwd: Path, on_update: Callable[[dict], Awaitable[None]] | None = None, on_permission: Callable[[dict], Awaitable[dict]] | None = None):
        self.command, self.cwd = command, cwd
        self.on_update, self.on_permission = on_update, on_permission
        self.session_id: str | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._active = False
        self._saw_partial_text = False

    async def start(self) -> dict:
        if not self.command or shutil.which(self.command[0]) is None:
            raise ClaudeStreamError(f"Claude executable unavailable: {self.command[0] if self.command else ''}; install Claude Code and log in.")
        return {"session_id": self.session_id}

    async def prompt(self, text: str) -> dict:
        if self._active:
            raise ClaudeStreamError("A Claude turn is already active")
        cmd = list(self.command)
        if self.session_id:
            cmd += ["--resume", self.session_id]
        cmd.append(text)
        self.process = await asyncio.create_subprocess_exec(*cmd, cwd=str(self.cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self._active = True
        self._saw_partial_text = False
        result: dict = {}
        try:
            assert self.process.stdout
            async for raw in self.process.stdout:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if event.get("session_id"):
                    self.session_id = event["session_id"]
                kind = event.get("type")
                if kind == "result":
                    result = event
                update = self._translate(event)
                if update and self.on_update:
                    await self.on_update(update)
            code = await self.process.wait()
            stderr = (await self.process.stderr.read()).decode(errors="replace")
            if code:
                message = result.get("result") or result.get("error") or stderr.strip() or f"Claude exited with status {code}"
                raise ClaudeStreamError(str(message))
            if result.get("is_error"):
                raise ClaudeStreamError(str(result.get("result") or "Claude reported an error"))
            return result
        finally:
            self._active = False
            self.process = None

    def _translate(self, event: dict) -> dict | None:
        kind = event.get("type")
        if kind == "stream_event":
            inner = event.get("event", {})
            delta = inner.get("delta", {})
            text = delta.get("text") or delta.get("thinking")
            if text:
                is_thought = delta.get("type") == "thinking_delta" or "thinking" in delta
                if not is_thought:
                    self._saw_partial_text = True
                return self._update("thought_chunk" if is_thought else "agent_message_chunk", {
                    "content": {"type": "text", "text": text}
                })
        if kind == "assistant":
            blocks = (event.get("message") or {}).get("content") or event.get("content") or []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return self._update("tool_call", {
                        "toolCallId": block.get("id", "claude-tool"),
                        "title": block.get("name", "Claude tool"),
                        "kind": "other",
                        "status": "pending",
                    })
            if not self._saw_partial_text:
                text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text")
                if text:
                    return self._update("agent_message_chunk", {"content": {"type": "text", "text": text}})
        if kind in {"tool_use", "tool_result"}:
            return self._update("tool_call_update", {
                "toolCallId": event.get("tool_use_id") or event.get("id", "claude-tool"),
                "status": "completed" if kind == "tool_result" else "in_progress",
                "content": event.get("content", []),
            })
        if kind == "error":
            return self._update("agent_message_chunk", {
                "content": {"type": "text", "text": str(event.get("error") or event.get("message") or "Claude error")}
            })
        return None

    def _update(self, update_type: str, fields: dict) -> dict:
        return {
            "sessionId": self.session_id or "claude-stream",
            "update": {"sessionUpdate": update_type, **fields},
        }

    async def cancel(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self._active = False

    async def close(self) -> None:
        await self.cancel()
