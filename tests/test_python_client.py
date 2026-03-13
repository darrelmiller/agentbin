"""
A2A Python SDK integration tests against deployed AgentBin service on Azure.

Tests the a2a-sdk client library and raw JSON-RPC against echo and spec agents.
"""

import asyncio
import json
import sys
import traceback
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.client.helpers import create_text_message_object
from a2a.types import a2a_pb2 as pb2

BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    tag = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))


def make_jsonrpc(method: str, text: str):
    """Build a raw JSON-RPC 2.0 request body."""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "id": str(uuid4()),
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            }
        },
    }


def extract_text(result: dict) -> str:
    """Pull first text part from a JSON-RPC result.
    Handles both message-only responses and task-wrapped responses."""
    # Direct message response
    msg = result.get("message", {})
    for p in msg.get("parts", []):
        if "text" in p:
            return p["text"]
    # Task-wrapped response
    task = result.get("task", {})
    status_msg = task.get("status", {}).get("message", {})
    for p in status_msg.get("parts", []):
        if "text" in p:
            return p["text"]
    for art in task.get("artifacts", []):
        for p in art.get("parts", []):
            if "text" in p:
                return p["text"]
    return ""


def extract_state(result: dict) -> str:
    """Extract task state — handles result.task.status.state wrapping."""
    # Task-wrapped: result.task.status.state
    task = result.get("task", {})
    state = task.get("status", {}).get("state", "")
    if state:
        return state
    # Direct: result.status.state
    return result.get("status", {}).get("state", "")


# ── SDK helper ──────────────────────────────────────────────────────

async def sdk_send(url: str, text: str, *, streaming: bool = False):
    """Send a message via the SDK and collect all events."""
    config = ClientConfig(
        streaming=streaming,
        httpx_client=httpx.AsyncClient(timeout=httpx.Timeout(30.0)),
    )
    client = await ClientFactory.connect(url, client_config=config)
    events = []
    final_task = None
    msg = create_text_message_object(role="ROLE_USER", content=text)
    async for stream_response, task in client.send_message(msg):
        events.append((stream_response, task))
        if task:
            final_task = task
    await config.httpx_client.aclose()
    return events, final_task


# ── 1. Agent card resolution ────────────────────────────────────────

async def test_resolve_echo_card():
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE}/echo")
        card = await resolver.get_agent_card()
        ok = card.name == "Echo Agent" and len(card.skills) > 0
        record("Resolve echo agent card", ok,
               f"name={card.name}, skills={[s.id for s in card.skills]}")


async def test_resolve_spec_card():
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE}/spec")
        card = await resolver.get_agent_card()
        skill_ids = [s.id for s in card.skills]
        ok = "Spec" in card.name and "streaming" in skill_ids
        record("Resolve spec agent card", ok,
               f"name={card.name}, skills={skill_ids}")


# ── 2. Echo via SDK ─────────────────────────────────────────────────

async def test_echo_sdk():
    events, _ = await sdk_send(f"{BASE}/echo", "Hello from Python SDK!")
    reply = ""
    for sr, _ in events:
        if sr.HasField("message"):
            for p in sr.message.parts:
                if p.text:
                    reply = p.text
    ok = reply.startswith("Echo:")
    record("Echo via SDK", ok, f"reply={reply!r}")


# ── 3. Spec: message-only ──────────────────────────────────────────

async def test_spec_message_only():
    events, _ = await sdk_send(f"{BASE}/spec", "message-only hello world")
    reply = ""
    got_message = False
    for sr, _ in events:
        if sr.HasField("message"):
            got_message = True
            for p in sr.message.parts:
                if p.text:
                    reply = p.text
    ok = got_message and len(reply) > 0
    record("Spec: message-only", ok, f"text={reply!r:.80}")


# ── 4. Spec: task-lifecycle ─────────────────────────────────────────

async def test_spec_task_lifecycle():
    events, task = await sdk_send(f"{BASE}/spec", "task-lifecycle process this")
    state = pb2.TaskState.Name(task.status.state) if task else "NO_TASK"
    has_artifact = bool(task and task.artifacts)
    ok = state == "TASK_STATE_COMPLETED" and has_artifact
    record("Spec: task-lifecycle", ok, f"state={state}, artifact={has_artifact}")


# ── 5. Spec: task-failure ──────────────────────────────────────────

async def test_spec_task_failure():
    events, task = await sdk_send(f"{BASE}/spec", "task-failure trigger error")
    state = pb2.TaskState.Name(task.status.state) if task else "NO_TASK"
    ok = state == "TASK_STATE_FAILED"
    record("Spec: task-failure", ok, f"state={state}")


# ── 6. Spec: streaming (SDK) ───────────────────────────────────────

async def test_spec_streaming_sdk():
    events, task = await sdk_send(
        f"{BASE}/spec", "streaming generate output", streaming=True
    )
    ok = len(events) >= 2
    final_text = ""
    if task:
        for art in task.artifacts:
            for p in art.parts:
                if p.text:
                    final_text = p.text
    for sr, _ in events:
        if sr.HasField("message"):
            for p in sr.message.parts:
                if p.text:
                    final_text = p.text
    record("Spec: streaming (SDK)", ok,
           f"events={len(events)}, text={final_text!r:.60}")


# ── 7. Spec: data-types ────────────────────────────────────────────

async def test_spec_data_types():
    events, task = await sdk_send(f"{BASE}/spec", "data-types show all")
    part_kinds: set[str] = set()
    for sr, t in events:
        sources = []
        if sr.HasField("message"):
            sources.append(sr.message.parts)
        cur_task = t or task
        if cur_task:
            for art in cur_task.artifacts:
                sources.append(art.parts)
        for parts in sources:
            for p in parts:
                if p.text:
                    part_kinds.add("text")
                if p.HasField("data"):
                    part_kinds.add("data")
                if p.url or p.raw:
                    part_kinds.add("file")
    ok = len(part_kinds) >= 2
    record("Spec: data-types", ok, f"kinds={part_kinds}")


# ── 8. Raw JSON-RPC: echo ──────────────────────────────────────────

async def test_raw_echo():
    body = make_jsonrpc("SendMessage", "hello from raw httpx")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resp = await hc.post(f"{BASE}/echo", json=body)
    data = resp.json()
    text = extract_text(data.get("result", {}))
    ok = resp.status_code == 200 and text.startswith("Echo:")
    record("Raw JSON-RPC: echo", ok, f"status={resp.status_code}, text={text!r}")


# ── 9. Raw JSON-RPC: spec message-only ─────────────────────────────

async def test_raw_spec_message_only():
    body = make_jsonrpc("SendMessage", "message-only raw test")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resp = await hc.post(f"{BASE}/spec", json=body)
    data = resp.json()
    text = extract_text(data.get("result", {}))
    ok = resp.status_code == 200 and len(text) > 0
    record("Raw JSON-RPC: spec message-only", ok,
           f"status={resp.status_code}, text={text!r}")


# ── 10. Raw JSON-RPC: spec task-lifecycle ──────────────────────────

async def test_raw_spec_task_lifecycle():
    body = make_jsonrpc("SendMessage", "task-lifecycle hello from raw")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resp = await hc.post(f"{BASE}/spec", json=body)
    data = resp.json()
    state = extract_state(data.get("result", {}))
    ok = resp.status_code == 200 and state in ("completed", "TASK_STATE_COMPLETED")
    record("Raw JSON-RPC: spec task-lifecycle", ok,
           f"status={resp.status_code}, state={state}")


# ── 11. Raw JSON-RPC: spec task-failure ────────────────────────────

async def test_raw_spec_task_failure():
    body = make_jsonrpc("SendMessage", "task-failure trigger error")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resp = await hc.post(f"{BASE}/spec", json=body)
    data = resp.json()
    state = extract_state(data.get("result", {}))
    ok = resp.status_code == 200 and state in ("failed", "TASK_STATE_FAILED")
    record("Raw JSON-RPC: spec task-failure", ok,
           f"status={resp.status_code}, state={state}")


# ── 12. Raw JSON-RPC: streaming (SSE) ──────────────────────────────

async def test_raw_spec_streaming_sse():
    """Test streaming via SendStreamingMessage with raw SSE parsing."""
    body = make_jsonrpc("SendStreamingMessage", "streaming generate output")
    chunks: list[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as hc:
        async with hc.stream(
            "POST", f"{BASE}/spec", json=body,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload:
                        chunks.append(json.loads(payload))
    ok = len(chunks) >= 2
    detail = f"chunks={len(chunks)}"
    if chunks:
        last_result = chunks[-1].get("result", {})
        detail += f", last_state={extract_state(last_result)}"
    record("Raw JSON-RPC: streaming (SSE)", ok, detail)


# ── 13. Raw JSON-RPC: data-types ───────────────────────────────────

async def test_raw_spec_data_types():
    body = make_jsonrpc("SendMessage", "data-types show all")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as hc:
        resp = await hc.post(f"{BASE}/spec", json=body)
    data = resp.json()
    result = data.get("result", {})
    task = result.get("task", {})
    kinds: set[str] = set()
    # Check artifacts inside the task wrapper
    for art in task.get("artifacts", []):
        for p in art.get("parts", []):
            if "text" in p:
                kinds.add("text")
            if "data" in p:
                kinds.add("data")
            if "file" in p:
                kinds.add("file")
    # Also check direct message
    msg = result.get("message", {})
    for p in msg.get("parts", []):
        if "text" in p:
            kinds.add("text")
        if "data" in p:
            kinds.add("data")
        if "file" in p:
            kinds.add("file")
    ok = resp.status_code == 200 and len(kinds) >= 2
    record("Raw JSON-RPC: data-types", ok,
           f"status={resp.status_code}, types={kinds}")


# ── Runner ──────────────────────────────────────────────────────────

ALL_TESTS = [
    ("Resolve echo agent card",         test_resolve_echo_card),
    ("Resolve spec agent card",          test_resolve_spec_card),
    ("Echo via SDK",                     test_echo_sdk),
    ("Spec: message-only",              test_spec_message_only),
    ("Spec: task-lifecycle",            test_spec_task_lifecycle),
    ("Spec: task-failure",              test_spec_task_failure),
    ("Spec: streaming (SDK)",           test_spec_streaming_sdk),
    ("Spec: data-types",               test_spec_data_types),
    ("Raw JSON-RPC: echo",             test_raw_echo),
    ("Raw JSON-RPC: spec message-only", test_raw_spec_message_only),
    ("Raw JSON-RPC: spec task-lifecycle", test_raw_spec_task_lifecycle),
    ("Raw JSON-RPC: spec task-failure", test_raw_spec_task_failure),
    ("Raw JSON-RPC: streaming (SSE)",   test_raw_spec_streaming_sse),
    ("Raw JSON-RPC: data-types",        test_raw_spec_data_types),
]


async def main():
    print(f"\n{'='*64}")
    print(f"  A2A Python SDK Integration Tests")
    print(f"  Target: {BASE}")
    print(f"{'='*64}\n")

    for label, fn in ALL_TESTS:
        try:
            await fn()
        except Exception as exc:
            record(label, False, f"EXCEPTION: {exc}")
            traceback.print_exc()

    # Summary table
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    print(f"\n{'='*64}")
    print(f"  RESULTS: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'='*64}")
    print(f"  {'Test':<40} {'Result':<6} Detail")
    print(f"  {'-'*40} {'-'*6} {'-'*50}")
    for name, p, detail in RESULTS:
        tag = "PASS" if p else "FAIL"
        print(f"  {name:<40} {tag:<6} {detail:.60}")
    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
