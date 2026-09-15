import asyncio
import sys
from pathlib import Path

from handoff.claude_stream import ClaudeStreamClient, ClaudeStreamError


SCRIPT = r'''import json, sys, time
prompt = sys.argv[-1]
if prompt == "slow":
    time.sleep(30)
if prompt == "bad":
    print(json.dumps({"type":"result", "session_id":"s1", "is_error":True, "result":"denied"}), flush=True)
    raise SystemExit(0)
print(json.dumps({"type":"stream_event", "session_id":"s1", "event":{"delta":{"type":"thinking_delta", "thinking":"plan"}}}), flush=True)
print(json.dumps({"type":"stream_event", "session_id":"s1", "event":{"delta":{"type":"text_delta", "text":prompt}}}), flush=True)
print(json.dumps({"type":"assistant", "session_id":"s1", "message":{"content":[{"type":"tool_use", "id":"t1", "name":"Read"}]}}), flush=True)
print(json.dumps({"type":"result", "session_id":"s1", "result":prompt}), flush=True)
'''


def test_stream_client_turn_resume_thought_and_tool(tmp_path: Path):
    script = tmp_path / "fake.py"
    script.write_text(SCRIPT, encoding="utf-8")
    updates = []

    async def run():
        async def on_update(item):
            updates.append(item)
        client = ClaudeStreamClient([sys.executable, str(script)], tmp_path, on_update)
        await client.start()
        first = await client.prompt("one")
        second = await client.prompt("two")
        await client.close()
        return first, second

    first, second = asyncio.run(run())
    assert first["session_id"] == "s1"
    assert second["result"] == "two"
    kinds = [item["update"]["sessionUpdate"] for item in updates]
    assert {"thought_chunk", "agent_message_chunk", "tool_call"} <= set(kinds)
    assert sum(item["update"].get("content", {}).get("text") == "two" for item in updates) == 1


def test_stream_client_surfaces_result_error_and_cancels(tmp_path: Path):
    script = tmp_path / "fake.py"
    script.write_text(SCRIPT, encoding="utf-8")

    async def run():
        client = ClaudeStreamClient([sys.executable, str(script)], tmp_path)
        await client.start()
        try:
            await client.prompt("bad")
        except ClaudeStreamError as exc:
            assert "denied" in str(exc)
        else:
            raise AssertionError("expected Claude result error")
        turn = asyncio.create_task(client.prompt("slow"))
        await asyncio.sleep(0.05)
        await client.cancel()
        try:
            await turn
        except ClaudeStreamError:
            pass
        assert client.process is None and not client._active
        await client.close()

    asyncio.run(run())
