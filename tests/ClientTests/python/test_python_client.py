"""
A2A Python SDK integration tests against AgentBin.

ALL tests use official SDK methods only — no raw HTTP or hand-crafted JSON-RPC.
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

import httpx
from importlib.metadata import version as pkg_version
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.client.client_factory import TransportProtocol
from a2a.client.helpers import create_text_message_object
from a2a.types import a2a_pb2 as pb2

_SDK_VERSION = pkg_version("a2a-sdk")


def _detect_sdk_source() -> str:
    """Detect whether the SDK was installed from a package manager or local/git source."""
    version = _SDK_VERSION
    # dev versions with git hashes indicate local or editable installs
    if ".dev" in version or "+g" in version or "+" in version:
        # Try to get the git branch from the installed package metadata
        try:
            from importlib.metadata import metadata
            meta = metadata("a2a-sdk")
            home = meta.get("Home-page", "") or ""
            if "a2a-python" in home or "a2aproject" in home:
                return f"a2a-python (local build, {version})"
        except Exception:
            pass
        return f"a2a-python (local build, {version})"
    return f"a2a-sdk {version}"


_SDK_SOURCE = _detect_sdk_source()

DEFAULT_BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE

RESULTS: list[dict] = []
_lifecycle_task_id: str | None = None
_rest_lifecycle_task_id: str | None = None


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


# -- SDK Helpers ------------------------------------------------------

A2A_HEADERS = {"A2A-Version": "1.0"}


async def make_client(url: str, *, streaming: bool = False, binding: str = "JSONRPC"):
    """Create an SDK client with the specified transport binding."""
    hc = httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=A2A_HEADERS)
    bindings = [TransportProtocol.HTTP_JSON] if binding == "REST" else [TransportProtocol.JSONRPC]
    config = ClientConfig(
        streaming=streaming,
        httpx_client=hc,
        supported_protocol_bindings=bindings,
    )
    client = await ClientFactory.connect(url, client_config=config)
    return client, hc


async def sdk_send(url: str, text: str, *, streaming: bool = False, binding: str = "JSONRPC"):
    """Send a message via the SDK and collect all events."""
    client, hc = await make_client(url, streaming=streaming, binding=binding)
    try:
        events = []
        final_task = None
        msg = create_text_message_object(role="ROLE_USER", content=text)
        req = pb2.SendMessageRequest(message=msg)
        async for stream_response, task in client.send_message(req):
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
    record("jsonrpc/agent-card-echo", "Echo Agent Card", ok,
           f"name={card.name}, skills={len(card.skills)}", ms)


async def test_agent_card_spec():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/spec")
        card = await resolver.get_agent_card()
    ms = int((time.time() - t0) * 1000)
    skill_ids = [s.id for s in card.skills]
    ok = "Spec" in card.name and len(card.skills) > 0
    record("jsonrpc/agent-card-spec", "Spec Agent Card", ok,
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
    record("jsonrpc/echo-send-message", "Echo Send Message", ok,
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
    record("jsonrpc/spec-message-only", "Spec Message Only", ok,
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
    record("jsonrpc/spec-task-lifecycle", "Spec Task Lifecycle", ok,
           f"state={state}, artifacts={has_artifact}, taskId={_lifecycle_task_id}", ms)


async def test_spec_get_task():
    """GetTask for the task created in spec-task-lifecycle via SDK."""
    t0 = time.time()
    task_id = _lifecycle_task_id
    if not task_id:
        record("jsonrpc/spec-get-task", "Spec GetTask", False, "skipped — no taskId from lifecycle", 0)
        return
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        task = await client.get_task(pb2.GetTaskRequest(id=task_id))
        ms = int((time.time() - t0) * 1000)
        state = task_state_name(task)
        ok = task.id == task_id and state == "TASK_STATE_COMPLETED"
        record("jsonrpc/spec-get-task", "Spec GetTask", ok,
               f"taskId={task.id}, state={state}", ms)
    finally:
        await hc.aclose()


async def test_spec_task_failure():
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "task-failure trigger error")
    ms = int((time.time() - t0) * 1000)
    state = task_state_name(task)
    ok = state == "TASK_STATE_FAILED"
    record("jsonrpc/spec-task-failure", "Spec Task Failure", ok,
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
    record("jsonrpc/spec-data-types", "Spec Data Types", ok,
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
    record("jsonrpc/spec-streaming", "Spec Streaming", ok,
           f"events={len(events)}, text={final_text!r:.50}", ms)


async def test_error_task_not_found():
    """GetTask with a nonexistent ID should raise an error."""
    t0 = time.time()
    fake_id = "00000000-0000-0000-0000-000000000000"
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        try:
            await client.get_task(pb2.GetTaskRequest(id=fake_id))
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-task-not-found", "Error Task Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-task-not-found", "Error Task Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_spec_multi_turn():
    """Multi-turn: 3-step conversation with task continuation via SDK."""
    t0 = time.time()
    hc = httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=A2A_HEADERS)
    try:
        config = ClientConfig(httpx_client=hc)
        client = await ClientFactory.connect(f"{BASE_URL}/spec", client_config=config)

        # Step 1: start conversation
        msg1 = create_text_message_object(role="ROLE_USER", content="multi-turn start conversation")
        task1 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg1)):
            if task:
                task1 = task

        state1 = task_state_name(task1)
        task_id = task1.id if task1 else None
        if state1 != "TASK_STATE_INPUT_REQUIRED" or not task_id:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/spec-multi-turn", "Spec Multi-Turn", False,
                   f"step1: expected INPUT_REQUIRED got {state1}", ms)
            return

        # Step 2: follow-up with same taskId
        msg2 = create_text_message_object(role="ROLE_USER", content="more data")
        msg2.task_id = task_id
        task2 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg2)):
            if task:
                task2 = task

        state2 = task_state_name(task2)
        if state2 != "TASK_STATE_INPUT_REQUIRED":
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/spec-multi-turn", "Spec Multi-Turn", False,
                   f"step2: expected INPUT_REQUIRED got {state2}", ms)
            return

        # Step 3: complete the conversation
        msg3 = create_text_message_object(role="ROLE_USER", content="done")
        msg3.task_id = task_id
        task3 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg3)):
            if task:
                task3 = task

        state3 = task_state_name(task3)
        ms = int((time.time() - t0) * 1000)
        ok = state3 == "TASK_STATE_COMPLETED"
        record("jsonrpc/spec-multi-turn", "Spec Multi-Turn", ok,
               f"states=[{state1},{state2},{state3}], taskId={task_id}", ms)
    finally:
        await hc.aclose()


async def test_spec_task_cancel():
    """Cancel a streaming task via SDK cancel_task method."""
    t0 = time.time()
    task_id = None
    canceled = False

    async def do_cancel():
        nonlocal task_id, canceled
        client, hc = await make_client(f"{BASE_URL}/spec", streaming=True)
        try:
            msg = create_text_message_object(role="ROLE_USER", content="task-cancel")
            async for _, task in client.send_message(pb2.SendMessageRequest(message=msg)):
                if task:
                    task_id = task.id
                    break

            if not task_id:
                return

            result = await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            state = task_state_name(result)
            canceled = state == "TASK_STATE_CANCELED"
        finally:
            await hc.aclose()

    await asyncio.wait_for(do_cancel(), timeout=10.0)
    ms = int((time.time() - t0) * 1000)
    ok = task_id is not None and canceled
    record("jsonrpc/spec-task-cancel", "Spec Task Cancel", ok,
           f"taskId={task_id}, canceled={canceled}", ms)


async def test_spec_list_tasks():
    """ListTasks via SDK list_tasks method."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        result = await client.list_tasks(pb2.ListTasksRequest())
        ms = int((time.time() - t0) * 1000)
        count = len(result.tasks)
        ok = count >= 1
        record("jsonrpc/spec-list-tasks", "Spec ListTasks", ok,
               f"taskCount={count}", ms)
    finally:
        await hc.aclose()


async def test_spec_return_immediately():
    """SendMessage with returnImmediately via SDK."""
    t0 = time.time()

    async def do_send():
        client, hc = await make_client(f"{BASE_URL}/spec")
        try:
            msg = create_text_message_object(role="ROLE_USER", content="long-running test")
            config = pb2.SendMessageConfiguration(return_immediately=True)
            req = pb2.SendMessageRequest(message=msg, configuration=config)
            final_task = None
            async for _, task in client.send_message(req):
                if task:
                    final_task = task
            return final_task
        finally:
            await hc.aclose()

    task = await asyncio.wait_for(do_send(), timeout=15.0)
    elapsed = time.time() - t0
    ms = int(elapsed * 1000)
    state = task_state_name(task)
    terminal = state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED")

    if elapsed < 2.0 and not terminal:
        ok = True
        detail = f"returned in {elapsed:.1f}s with state={state}"
    else:
        ok = False
        if elapsed >= 3.0:
            detail = f"returnImmediately ignored by SDK — blocked {elapsed:.1f}s, state={state}"
        else:
            detail = f"returnImmediately ignored by SDK — got terminal state={state} in {elapsed:.1f}s"

    record("jsonrpc/spec-return-immediately", "Spec Return Immediately", ok,
           detail, ms)


# -- REST Tests (via SDK HTTP+JSON transport) ----------------------------

async def test_rest_agent_card_echo():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        config = ClientConfig(
            httpx_client=hc,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
        client = await ClientFactory.connect(f"{BASE_URL}/echo", client_config=config)
    ms = int((time.time() - t0) * 1000)
    # If we got here, the card was resolved and REST transport was selected
    record("rest/agent-card-echo", "REST Echo Agent Card", True,
           "card resolved with HTTP+JSON transport", ms)


async def test_rest_agent_card_spec():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        config = ClientConfig(
            httpx_client=hc,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
        client = await ClientFactory.connect(f"{BASE_URL}/spec", client_config=config)
    ms = int((time.time() - t0) * 1000)
    record("rest/agent-card-spec", "REST Spec Agent Card", True,
           "card resolved with HTTP+JSON transport", ms)


async def test_rest_echo_send_message():
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/echo", "Hello from Python SDK REST!", binding="REST")
    ms = int((time.time() - t0) * 1000)
    reply = ""
    for sr, _ in events:
        if sr.HasField("message"):
            for p in sr.message.parts:
                if p.text:
                    reply = p.text
    ok = reply.startswith("Echo:")
    record("rest/echo-send-message", "REST Echo Send Message", ok,
           f"reply={reply!r}", ms)


async def test_rest_spec_message_only():
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/spec", "message-only hello world", binding="REST")
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
    record("rest/spec-message-only", "REST Spec Message Only", ok,
           f"gotMessage={got_message}, text={reply!r:.60}", ms)


async def test_rest_spec_task_lifecycle():
    global _rest_lifecycle_task_id
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "task-lifecycle process this", binding="REST")
    ms = int((time.time() - t0) * 1000)
    state = task_state_name(task)
    has_artifact = bool(task and task.artifacts)
    if task:
        _rest_lifecycle_task_id = task.id
    ok = state == "TASK_STATE_COMPLETED" and has_artifact
    record("rest/spec-task-lifecycle", "REST Spec Task Lifecycle", ok,
           f"state={state}, artifacts={has_artifact}, taskId={_rest_lifecycle_task_id}", ms)


async def test_rest_spec_get_task():
    t0 = time.time()
    task_id = _rest_lifecycle_task_id
    if not task_id:
        record("rest/spec-get-task", "REST Spec GetTask", False, "skipped — no taskId from lifecycle", 0)
        return
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        task = await client.get_task(pb2.GetTaskRequest(id=task_id))
        ms = int((time.time() - t0) * 1000)
        state = task_state_name(task)
        ok = task.id == task_id and state == "TASK_STATE_COMPLETED"
        record("rest/spec-get-task", "REST Spec GetTask", ok,
               f"taskId={task.id}, state={state}", ms)
    finally:
        await hc.aclose()


async def test_rest_spec_task_failure():
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "task-failure trigger error", binding="REST")
    ms = int((time.time() - t0) * 1000)
    state = task_state_name(task)
    ok = state == "TASK_STATE_FAILED"
    record("rest/spec-task-failure", "REST Spec Task Failure", ok,
           f"state={state}", ms)


async def test_rest_spec_data_types():
    t0 = time.time()
    events, task = await sdk_send(f"{BASE_URL}/spec", "data-types show all", binding="REST")
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
    record("rest/spec-data-types", "REST Spec Data Types", ok,
           f"kinds={sorted(part_kinds)}", ms)


async def test_rest_spec_streaming():
    t0 = time.time()
    events, task = await sdk_send(
        f"{BASE_URL}/spec", "streaming generate output", streaming=True, binding="REST",
    )
    ms = int((time.time() - t0) * 1000)
    ok = len(events) >= 2
    record("rest/spec-streaming", "REST Spec Streaming", ok,
           f"events={len(events)}", ms)


async def test_rest_error_task_not_found():
    t0 = time.time()
    fake_id = "00000000-0000-0000-0000-000000000000"
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        try:
            await client.get_task(pb2.GetTaskRequest(id=fake_id))
            ms = int((time.time() - t0) * 1000)
            record("rest/error-task-not-found", "REST Error Task Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-task-not-found", "REST Error Task Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_spec_multi_turn():
    """Multi-turn: 3-step conversation via REST binding using SDK."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        # Step 1: start conversation
        msg1 = create_text_message_object(role="ROLE_USER", content="multi-turn start conversation")
        task1 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg1)):
            if task:
                task1 = task

        state1 = task_state_name(task1)
        task_id = task1.id if task1 else None
        if state1 != "TASK_STATE_INPUT_REQUIRED" or not task_id:
            ms = int((time.time() - t0) * 1000)
            record("rest/spec-multi-turn", "REST Spec Multi-Turn", False,
                   f"step1: expected INPUT_REQUIRED got {state1}", ms)
            return

        # Step 2: follow-up with same taskId
        msg2 = create_text_message_object(role="ROLE_USER", content="more data")
        msg2.task_id = task_id
        task2 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg2)):
            if task:
                task2 = task

        state2 = task_state_name(task2)
        if state2 != "TASK_STATE_INPUT_REQUIRED":
            ms = int((time.time() - t0) * 1000)
            record("rest/spec-multi-turn", "REST Spec Multi-Turn", False,
                   f"step2: expected INPUT_REQUIRED got {state2}", ms)
            return

        # Step 3: complete the conversation
        msg3 = create_text_message_object(role="ROLE_USER", content="done")
        msg3.task_id = task_id
        task3 = None
        async for _, task in client.send_message(pb2.SendMessageRequest(message=msg3)):
            if task:
                task3 = task

        state3 = task_state_name(task3)
        ms = int((time.time() - t0) * 1000)
        ok = state3 == "TASK_STATE_COMPLETED"
        record("rest/spec-multi-turn", "REST Spec Multi-Turn", ok,
               f"states=[{state1},{state2},{state3}], taskId={task_id}", ms)
    finally:
        await hc.aclose()


async def test_rest_spec_task_cancel():
    """Cancel a streaming task via REST binding using SDK cancel_task."""
    t0 = time.time()
    task_id = None
    canceled = False

    async def do_cancel():
        nonlocal task_id, canceled
        client, hc = await make_client(f"{BASE_URL}/spec", streaming=True, binding="REST")
        try:
            msg = create_text_message_object(role="ROLE_USER", content="task-cancel")
            async for _, task in client.send_message(pb2.SendMessageRequest(message=msg)):
                if task:
                    task_id = task.id
                    break

            if not task_id:
                return

            result = await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            state = task_state_name(result)
            canceled = state == "TASK_STATE_CANCELED"
        finally:
            await hc.aclose()

    await asyncio.wait_for(do_cancel(), timeout=10.0)
    ms = int((time.time() - t0) * 1000)
    ok = task_id is not None and canceled
    record("rest/spec-task-cancel", "REST Spec Task Cancel", ok,
           f"taskId={task_id}, canceled={canceled}", ms)


async def test_rest_spec_list_tasks():
    """List tasks via SDK list_tasks with REST binding."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        result = await client.list_tasks(pb2.ListTasksRequest())
        ms = int((time.time() - t0) * 1000)
        count = len(result.tasks)
        ok = count >= 1
        record("rest/spec-list-tasks", "REST Spec ListTasks", ok,
               f"taskCount={count}", ms)
    finally:
        await hc.aclose()


async def test_rest_spec_return_immediately():
    """REST SendMessage with returnImmediately via SDK."""
    t0 = time.time()

    async def do_send():
        client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
        try:
            msg = create_text_message_object(role="ROLE_USER", content="long-running test")
            config = pb2.SendMessageConfiguration(return_immediately=True)
            req = pb2.SendMessageRequest(message=msg, configuration=config)
            final_task = None
            async for _, task in client.send_message(req):
                if task:
                    final_task = task
            return final_task
        finally:
            await hc.aclose()

    task = await asyncio.wait_for(do_send(), timeout=15.0)
    elapsed = time.time() - t0
    ms = int(elapsed * 1000)
    state = task_state_name(task)
    terminal = state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED")

    if elapsed < 2.0 and not terminal:
        ok = True
        detail = f"returned in {elapsed:.1f}s with state={state}"
    else:
        ok = False
        if elapsed >= 3.0:
            detail = f"returnImmediately ignored by SDK — blocked {elapsed:.1f}s, state={state}"
        else:
            detail = f"returnImmediately ignored by SDK — got terminal state={state} in {elapsed:.1f}s"

    record("rest/spec-return-immediately", "REST Spec Return Immediately", ok,
           detail, ms)


# -- Runner -----------------------------------------------------------

ALL_TESTS = [
    # JSON-RPC (SDK) tests
    ("jsonrpc/agent-card-echo",         test_agent_card_echo),
    ("jsonrpc/agent-card-spec",         test_agent_card_spec),
    ("jsonrpc/echo-send-message",       test_echo_send_message),
    ("jsonrpc/spec-message-only",       test_spec_message_only),
    ("jsonrpc/spec-task-lifecycle",     test_spec_task_lifecycle),
    ("jsonrpc/spec-get-task",           test_spec_get_task),
    ("jsonrpc/spec-task-failure",       test_spec_task_failure),
    ("jsonrpc/spec-data-types",         test_spec_data_types),
    ("jsonrpc/spec-streaming",          test_spec_streaming),
    ("jsonrpc/error-task-not-found",    test_error_task_not_found),
    ("jsonrpc/spec-multi-turn",         test_spec_multi_turn),
    ("jsonrpc/spec-task-cancel",        test_spec_task_cancel),
    ("jsonrpc/spec-list-tasks",         test_spec_list_tasks),
    ("jsonrpc/spec-return-immediately", test_spec_return_immediately),
    # REST binding tests
    ("rest/agent-card-echo",            test_rest_agent_card_echo),
    ("rest/agent-card-spec",            test_rest_agent_card_spec),
    ("rest/echo-send-message",          test_rest_echo_send_message),
    ("rest/spec-message-only",          test_rest_spec_message_only),
    ("rest/spec-task-lifecycle",        test_rest_spec_task_lifecycle),
    ("rest/spec-get-task",              test_rest_spec_get_task),
    ("rest/spec-task-failure",          test_rest_spec_task_failure),
    ("rest/spec-data-types",            test_rest_spec_data_types),
    ("rest/spec-streaming",             test_rest_spec_streaming),
    ("rest/error-task-not-found",       test_rest_error_task_not_found),
    ("rest/spec-multi-turn",            test_rest_spec_multi_turn),
    ("rest/spec-task-cancel",           test_rest_spec_task_cancel),
    ("rest/spec-list-tasks",            test_rest_spec_list_tasks),
    ("rest/spec-return-immediately",    test_rest_spec_return_immediately),
]


async def main():
    print(f"\n{'='*64}")
    print(f"  A2A Python SDK Integration Tests  ({_SDK_SOURCE})")
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
        "sdk": _SDK_SOURCE,
        "protocolVersion": "1.0",
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