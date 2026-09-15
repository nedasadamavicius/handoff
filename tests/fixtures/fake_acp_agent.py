import json
import sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()

pending_prompt = None
for line in sys.stdin:
    try: msg = json.loads(line)
    except Exception: continue
    method, ident, p = msg.get("method"), msg.get("id"), msg.get("params", {})
    if ident == 99 and "result" in msg and pending_prompt is not None:
        send({"jsonrpc":"2.0", "id":pending_prompt, "result":{"stopReason":"end_turn"}})
        pending_prompt = None
        continue
    if method == "initialize":
        assert p == {"protocolVersion": 1, "clientCapabilities": {}, "clientInfo": {"name": "handoff", "version": "0.1.0"}}
        send({"jsonrpc":"2.0", "id":ident, "result":{"protocolVersion":1}})
    elif method == "session/new":
        assert p.get("mcpServers") == [] and p.get("cwd")
        send({"jsonrpc":"2.0", "id":ident, "result":{"sessionId":"fake-session"}})
    elif method == "session/prompt":
        sid = p.get("sessionId")
        text = p.get("prompt", [{}])[0].get("text", "")
        if text == "permission":
            pending_prompt = ident
            send({"jsonrpc":"2.0", "id":99, "method":"session/request_permission", "params":{"options":[{"optionId":"allow"}]}})
            continue
        if text == "error":
            send({"jsonrpc":"2.0", "id":ident, "error":{"code":-32000,"message":"failed"}})
            continue
        if text == "die":
            sys.stderr.write("fixture exploded while handling the turn\n")
            sys.stderr.flush()
            sys.exit(3)
        if text == "unknown":
            pending_prompt = ident
            send({"jsonrpc":"2.0", "id":98, "method":"client/not_real", "params":{}})
            continue
        send({"jsonrpc":"2.0", "method":"session/update", "params":{"sessionId":sid,"update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"hello"}}}})
        send({"jsonrpc":"2.0", "method":"session/update", "params":{"sessionId":sid,"update":{"sessionUpdate":"tool_call","toolCall":{"name":"fake"}}}})
        send({"jsonrpc":"2.0", "method":"session/update", "params":{"sessionId":sid,"update":{"sessionUpdate":"thought_chunk","content":{"type":"text","text":"thinking"}}}})
        send({"jsonrpc":"2.0", "id":ident, "result":{"stopReason":"end_turn"}})
    elif method == "session/cancel":
        pass
    elif ident == 98 and msg.get("error", {}).get("code") == -32601 and pending_prompt is not None:
        send({"jsonrpc":"2.0", "id":pending_prompt, "result":{"stopReason":"end_turn"}})
        pending_prompt = None
