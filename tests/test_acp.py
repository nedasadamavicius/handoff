import asyncio
import sys
from pathlib import Path

from handoff.acp import ACPClient, ACPError

FIXTURE = Path(__file__).parent / "fixtures" / "fake_acp_agent.py"

def run(coro):
    return asyncio.run(coro)

def test_handshake_prompt_and_update(tmp_path):
    async def scenario():
        updates = []
        async def receive(params):
            updates.append(params)
        client = ACPClient([sys.executable, str(FIXTURE)], tmp_path,
                           on_update=receive)
        await client.start()
        result = await client.prompt("hi")
        assert result["stopReason"] == "end_turn"
        assert updates[0]["update"]["content"]["text"] == "hello"
        assert {item["update"]["sessionUpdate"] for item in updates} == {"agent_message_chunk", "tool_call", "thought_chunk"}
        assert client.session_id == "fake-session"
        await client.close(); await client.close()
    run(scenario())

def test_prompt_turns_cannot_overlap(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        async def permission(_):
            entered.set()
            await release.wait()
            return "allow"
        client = ACPClient([sys.executable, str(FIXTURE)], tmp_path, on_permission=permission)
        await client.start()
        first = asyncio.create_task(client.prompt("permission"))
        await asyncio.wait_for(entered.wait(), 1)
        try:
            await client.prompt("two")
        except ACPError as exc:
            assert "already" in str(exc)
        else:
            raise AssertionError("expected overlapping prompt rejection")
        release.set()
        await first
        await client.close()
    run(scenario())

def test_permission_selection_and_cancelled_default(tmp_path):
    async def scenario():
        async def permission(_): return "allow"
        client = ACPClient([sys.executable, str(FIXTURE)], tmp_path, on_permission=permission)
        await client.start()
        assert await client.prompt("permission") is None or True
        await client.close()
        assert client._permission_result({"options":[{"optionId":"allow"}]}, "allow") == {"outcome":{"outcome":"selected","optionId":"allow"}}
        assert client._permission_result({"options":[{"optionId":"allow"}]}, "bad") == {"outcome":{"outcome":"cancelled"}}
        await client.close()
    run(scenario())

def test_rpc_error_and_process_death(tmp_path):
    async def scenario():
        client = ACPClient([sys.executable, str(FIXTURE)], tmp_path)
        await client.start()
        try:
            await client.prompt("error")
        except ACPError:
            pass
        else: raise AssertionError("expected RPC error")
        try:
            await client.prompt("die")
        except ACPError as exc:
            assert "status 3" in str(exc)
            assert "fixture exploded" in str(exc)
        else: raise AssertionError("expected process death error")
        await client.close()
    run(scenario())


def test_update_callback_failure_does_not_kill_transport(tmp_path):
    async def scenario():
        reported = []

        async def broken_update(_):
            raise RuntimeError("renderer broke")

        async def report(error):
            reported.append(str(error))

        client = ACPClient(
            [sys.executable, str(FIXTURE)], tmp_path,
            on_update=broken_update, on_error=report,
        )
        await client.start()
        assert (await client.prompt("hi"))["stopReason"] == "end_turn"
        assert (await client.prompt("hi"))["stopReason"] == "end_turn"
        assert reported and "renderer broke" in reported[0]
        assert client.process and client.process.returncode is None
        await client.close()

    run(scenario())


def test_cancel_resolves_waiting_permission_and_unknown_request(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        never = asyncio.Event()
        async def permission(_):
            entered.set()
            await never.wait()
            return "allow"
        client = ACPClient([sys.executable, str(FIXTURE)], tmp_path, on_permission=permission)
        await client.start()
        turn = asyncio.create_task(client.prompt("permission"))
        await asyncio.wait_for(entered.wait(), 1)
        await client.cancel()
        assert (await asyncio.wait_for(turn, 1))["stopReason"] == "end_turn"
        assert (await client.prompt("unknown"))["stopReason"] == "end_turn"
        await client.close()
    run(scenario())

def test_start_failure_is_acp_error(tmp_path):
    async def scenario():
        client = ACPClient([sys.executable, str(tmp_path / "missing.py")], tmp_path)
        try:
            await client.start()
        except (ACPError, OSError):
            pass
        else:
            raise AssertionError("expected startup failure")
        await client.close()
    run(scenario())
