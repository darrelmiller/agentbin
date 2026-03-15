"""
A2A Python SDK (v0.3.25) standardized integration tests against AgentBin.

Outputs human-readable console results AND a results.json file.
Usage: python test_python_client.py [baseUrl]
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.client.helpers import create_text_message_object
from a2a.types import a2a_pb2 as pb2

DEFAULT_BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE

RESULTS: list[dict] = []
# Stash the task ID from spec-task-lifecycle so spec-get-task can reuse it
_lifecycle_task_id: str | None = None


def record(test_id: str, name: str, passed: bool, detail: str, duration_ms: int):
    tag = "PASS" if passed else "FAIL"
    RESULTS.append({
        "id": test_id,
        "name": name,
        "passed": passed,
        "detail": detail,
        "durationMs": duration_ms,
    })
    print(f"  [{tag}] {test_id} \u2014 {detail}")


# -- Helpers ----------------------------------------------------------

def make_jsonrpc(method: str, params: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "id": str(uuid4()),
        "params": params,
    }


def make_send_params(text: str) -> dict:
    return {
        "message": {
            "messageId": str(uuid4()),
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        }
    }


A2A_HEADERS = {"A2A-Version": "1.0"}


async def sdk_send(url: str, text: str, *, streaming: bool = False):
    """Send a message via the SDK and collect all events."""
    hc = httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=A2A_HEADERS)
    try:
        config = ClientConfig(streaming=streaming, httpx_client=hc)
        client = await ClientFactory.connect(url, client_config=config)
        events = []
        final_task = None
        msg = create_text_message_object(role="ROLE_USER", content=text)
        async for stream_response, task in client.send_message(msg):
            events.append((stream_response, task))
            if task:
                final_task = task
        return events, final_task
    finally:
        await hc.aclose()


def task_state_name(task) -> str:
    """Get human-readable task state from a protobuf task object."""
    if not task:
        return "NO_TASK"
    return pb2.TaskState.Name(task.status.state)


# -- Tests ------------------------------------------------------------

async def test_agent_card_echo():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/echo")
        card = await resolver.get_agent_card()
    ms = int((time.time() - t0) * 1000)
    ok = card.name == "Echo Agent" and len(card.skills) > 0
    record("agent-card-echo", "Echo Agent Card", ok,
           f"name={card.name}, skills={len(card.skills)}", ms)


async def test_agent_card_spec():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/spec")
        card = await resolver.get_agent_card()
    ms = int((time.time() - t0) * 1000)
    skill_ids = [s.id for s in card.skills]
    ok = "Spec" in card.name and len(card.skills) > 0
    record("agent-card-spec", "Spec Agent Card", ok,
           f"name={card.name}, skills={skill_ids}", ms)


async def test_echo_send_message():
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/echo", "Hello from Python SDK!")
    ms = int((time.time() - t0) * 1000)
    reply = ""
    for sr, _ in events:
        if sr.HasField("message"):
            for p in sr.message.parts:
                if p.text:
                    reply = p.text
    ok = reply.startswith("Echo:")
    record("echo-send-message", "Echo Send Message", ok,
           f"reply={reply!r}", ms)


async def test_spec_message_only():
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/spec", "message-only hello world")
    ms = int((time.time() - t0) * 1000)
    reply = ""
    got_message = False
    for sr, _ in events:
        if sr.HasField("message"):
            got_message = True
            for p in sr.message.parts:
                if p.text:
                    reply = p.text
    ok = got_message and len(reply) > 0
    record("spec-message-only", "Spec Message Only", ok,
           f"gotMessage={got_message}, text={reply!r:.60}", ms)


async def test_spec_task_lifecycle():
    global _lifecycle_task_id
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "task-lifecycle process this")
    ms = int((time.time() - t0) * 1000)
    state = task_state_name(task)
    has_artifact = bool(task and task.artifacts)
    if task:
        _lifecycle_task_id = task.id
    ok = state == "TASK_STATE_COMPLETED" and has_artifact
    record("spec-task-lifecycle", "Spec Task Lifecycle", ok,
           f"state={state}, artifacts={has_artifact}, taskId={_lifecycle_task_id}", ms)


async def test_spec_get_task():
    """GetTask for the task created in spec-task-lifecycle via raw JSON-RPC."""
    t0 = time.time()
    task_id = _lifecycle_task_id or str(uuid4())
    body = make_jsonrpc("GetTask", {"id": task_id})
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        resp = await hc.post(f"{BASE_URL}/spec", json=body)
    ms = int((time.time() - t0) * 1000)
    data = resp.json()
    result = data.get("result", {})
    # The result may be the task directly or wrapped in result.task
    task_obj = result.get("task", result) if isinstance(result, dict) else {}
    got_id = task_obj.get("id", "")
    state = task_obj.get("status", {}).get("state", "")
    ok = resp.status_code == 200 and got_id == task_id and state in (
        "completed", "TASK_STATE_COMPLETED",
    )
    record("spec-get-task", "Spec GetTask", ok,
           f"taskId={got_id}, state={state}", ms)


async def test_spec_task_failure():
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "task-failure trigger error")
    ms = int((time.time() - t0) * 1000)
    state = task_state_name(task)
    ok = state == "TASK_STATE_FAILED"
    record("spec-task-failure", "Spec Task Failure", ok,
           f"state={state}", ms)


async def test_spec_data_types():
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "data-types show all")
    ms = int((time.time() - t0) * 1000)
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
    record("spec-data-types", "Spec Data Types", ok,
           f"kinds={sorted(part_kinds)}", ms)


async def test_spec_streaming():
    t0 = time.time()
    events, task = await sdk_send(
        f"{BASE_URL}/spec", "streaming generate output", streaming=True,
    )
    ms = int((time.time() - t0) * 1000)
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
    record("spec-streaming", "Spec Streaming", ok,
           f"events={len(events)}, text={final_text!r:.50}", ms)


async def test_error_task_not_found():
    """GetTask with a nonexistent ID should return a JSON-RPC error."""
    t0 = time.time()
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = make_jsonrpc("GetTask", {"id": fake_id})
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        resp = await hc.post(f"{BASE_URL}/spec", json=body)
    ms = int((time.time() - t0) * 1000)
    data = resp.json()
    has_error = "error" in data
    error_code = data.get("error", {}).get("code", "")
    error_msg = data.get("error", {}).get("message", "")
    ok = has_error
    record("error-task-not-found", "Error Task Not Found", ok,
           f"hasError={has_error}, code={error_code}, msg={error_msg!r:.40}", ms)


# -- Runner -----------------------------------------------------------

ALL_TESTS = [
    ("agent-card-echo",       test_agent_card_echo),
    ("agent-card-spec",       test_agent_card_spec),
    ("echo-send-message",     test_echo_send_message),
    ("spec-message-only",     test_spec_message_only),
    ("spec-task-lifecycle",   test_spec_task_lifecycle),
    ("spec-get-task",         test_spec_get_task),
    ("spec-task-failure",     test_spec_task_failure),
    ("spec-data-types",       test_spec_data_types),
    ("spec-streaming",        test_spec_streaming),
    ("error-task-not-found",  test_error_task_not_found),
]


async def main():
    print(f"\n{'='*64}")
    print(f"  A2A Python SDK Integration Tests  (a2a-sdk 0.3.25)")
    print(f"  Target: {BASE_URL}")
    print(f"{'='*64}\n")

    for test_id, fn in ALL_TESTS:
        try:
            await fn()
        except Exception as exc:
            ms = 0
            record(test_id, test_id, False, f"EXCEPTION: {exc}", ms)
            traceback.print_exc()

    # Console summary
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"\n{'='*64}")
    print(f"  TOTAL: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'='*64}\n")

    # Write results.json alongside this script
    output = {
        "client": "python",
        "sdk": "a2a-sdk 0.3.25",
        "protocolVersion": "0.3",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseUrl": BASE_URL,
        "results": RESULTS,
    }
    results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"  Results written to {results_path}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))