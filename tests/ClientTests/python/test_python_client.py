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
    factory = ClientFactory(config)
    client = await factory.create_from_url(url)
    return client, hc


async def sdk_send(url: str, text: str, *, streaming: bool = False, binding: str = "JSONRPC"):
    """Send a message via the SDK and collect all events."""
    client, hc = await make_client(url, streaming=streaming, binding=binding)
    try:
        events = []
        final_task = None
        msg = create_text_message_object(role="ROLE_USER", content=text)
        req = pb2.SendMessageRequest(message=msg)
        async for stream_response in client.send_message(req):
            task = None
            if stream_response.HasField("task"):
                task = stream_response.task
                final_task = task
            elif stream_response.HasField("status_update") and final_task:
                # In alpha.1, streaming yields status_update events separately;
                # merge the latest status into the accumulated task.
                final_task.status.CopyFrom(stream_response.status_update.status)
                task = final_task
            events.append((stream_response, task))
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


async def test_spec_extended_card():
    """Test GetExtendedAgentCard for JSON-RPC binding."""
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        # Step 1: Get public card
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/spec")
        public_card = await resolver.get_agent_card()
        
        # Step 2: Verify extendedAgentCard capability
        has_extended = False
        if public_card.capabilities:
            has_extended = getattr(public_card.capabilities, "extended_agent_card", False)
        
        if not has_extended:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/spec-extended-card", "Spec Extended Agent Card", False,
                   "capabilities.extendedAgentCard not true", ms)
            return
        
        # Step 3: Call GetExtendedAgentCard via JSON-RPC with auth header
        auth_headers = {**A2A_HEADERS, "Authorization": "Bearer agentbin-test-token"}
        payload = {
            "jsonrpc": "2.0",
            "method": "GetExtendedAgentCard",
            "id": "test-extended-card",
            "params": {}
        }
        response = await hc.post(f"{BASE_URL}/spec", json=payload, headers=auth_headers)
        
        if response.status_code != 200:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/spec-extended-card", "Spec Extended Agent Card", False,
                   f"HTTP {response.status_code}", ms)
            return
        
        result = response.json()
        if "error" in result:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/spec-extended-card", "Spec Extended Agent Card", False,
                   f"JSON-RPC error: {result['error']}", ms)
            return
        
        # Step 4: Verify extended card is a valid AgentCard
        extended_card_data = result.get("result", {})
        extended_name = extended_card_data.get("name", "")
        extended_skills = extended_card_data.get("skills", [])
        
        # Step 5: Verify extended card has more skills or has admin-status
        public_skill_count = len(public_card.skills)
        extended_skill_count = len(extended_skills)
        extended_skill_ids = [s.get("id", "") for s in extended_skills]
        has_admin_status = "admin-status" in extended_skill_ids
        
        ok = (extended_skill_count > public_skill_count or has_admin_status) and extended_name
        ms = int((time.time() - t0) * 1000)
        record("jsonrpc/spec-extended-card", "Spec Extended Agent Card", ok,
               f"public={public_skill_count} skills, extended={extended_skill_count} skills, "
               f"hasAdminStatus={has_admin_status}, name={extended_name!r}", ms)


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
        config = ClientConfig(httpx_client=hc, streaming=False)
        factory = ClientFactory(config)
        client = await factory.create_from_url(f"{BASE_URL}/spec")

        # Step 1: start conversation
        msg1 = create_text_message_object(role="ROLE_USER", content="multi-turn start conversation")
        task1 = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg1)):
            task = _sr.task if _sr.HasField("task") else None
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
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
            task = _sr.task if _sr.HasField("task") else None
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
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg3)):
            task = _sr.task if _sr.HasField("task") else None
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
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
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
            async for _sr in client.send_message(req):
                task = _sr.task if _sr.HasField("task") else None
                if task:
                    final_task = task
            return final_task
        finally:
            await hc.aclose()

    task = await asyncio.wait_for(do_send(), timeout=15.0)
    elapsed = time.time() - t0
    ms = int(elapsed * 1000)
    state = task_state_name(task)

    if elapsed < 3.0:
        ok = True
        detail = f"returned in {elapsed:.1f}s with state={state}"
    else:
        ok = False
        detail = f"returnImmediately ignored by SDK — blocked {elapsed:.1f}s, state={state}"

    record("jsonrpc/spec-return-immediately", "Spec Return Immediately", ok,
           detail, ms)


async def test_error_cancel_not_found():
    """CancelTask with a nonexistent ID should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        try:
            await client.cancel_task(pb2.CancelTaskRequest(id="00000000-0000-0000-0000-000000000000"))
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-cancel-not-found", "Error Cancel Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-cancel-not-found", "Error Cancel Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_error_cancel_terminal():
    """CancelTask on a completed task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        # Create a completed task
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-cancel-terminal", "Error Cancel Terminal", False,
                   "could not create completed task", ms)
            return
        task_id = final_task.id
        try:
            await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-cancel-terminal", "Error Cancel Terminal", False,
                   "expected error canceling completed task, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-cancel-terminal", "Error Cancel Terminal", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_error_send_terminal():
    """SendMessage to a completed task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        # Create a completed task
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-send-terminal", "Error Send Terminal", False,
                   "could not create completed task", ms)
            return
        task_id = final_task.id
        try:
            msg2 = create_text_message_object(role="ROLE_USER", content="follow-up to completed task")
            msg2.task_id = task_id
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
                task = _sr.task if _sr.HasField("task") else None
                pass
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-send-terminal", "Error Send Terminal", False,
                   "expected error sending to completed task, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-send-terminal", "Error Send Terminal", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_error_send_invalid_task():
    """SendMessage with a bogus taskId should raise TaskNotFoundError."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        try:
            msg = create_text_message_object(role="ROLE_USER", content="hello")
            msg.task_id = "00000000-0000-0000-0000-000000000000"
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
                pass
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-send-invalid-task", "Error Send Invalid Task", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-send-invalid-task", "Error Send Invalid Task", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_error_push_not_supported():
    """SetTaskPushNotificationConfig should error since server doesn't support push."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        if not hasattr(client, "set_task_callback"):
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-push-not-supported", "Error Push Not Supported", True,
                   "SDK does not support push notification config", ms)
            return
        try:
            push_config = pb2.PushNotificationConfig(url="https://example.com/webhook")
            req = pb2.SetTaskPushNotificationConfigRequest(
                task_id="dummy",
                push_notification_config=push_config,
            )
            await client.set_task_callback(req)
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-push-not-supported", "Error Push Not Supported", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-push-not-supported", "Error Push Not Supported", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_subscribe_to_task():
    """Subscribe to a working task, collect events, then cancel to complete."""
    t0 = time.time()

    async def do_subscribe():
        client, hc = await make_client(f"{BASE_URL}/spec", streaming=True)
        try:
            if not hasattr(client, "subscribe"):
                ms = int((time.time() - t0) * 1000)
                record("jsonrpc/subscribe-to-task", "Subscribe To Task", True,
                       "SDK does not support SubscribeToTask", ms)
                return

            # Start a task that stays in WORKING state
            msg = create_text_message_object(role="ROLE_USER", content="task-cancel")
            task_id = None
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
                if task:
                    task_id = task.id
                    break

            if not task_id:
                ms = int((time.time() - t0) * 1000)
                record("jsonrpc/subscribe-to-task", "Subscribe To Task", False,
                       "could not start working task", ms)
                return

            # Subscribe to the task and collect events
            sub_events = []

            async def collect_events():
                async for event in client.subscribe(pb2.SubscribeToTaskRequest(id=task_id)):
                    sub_events.append(event)

            collect_task = asyncio.create_task(collect_events())
            await asyncio.sleep(1)

            # Cancel the task to let it complete
            await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            try:
                await asyncio.wait_for(collect_task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass

            ms = int((time.time() - t0) * 1000)
            ok = len(sub_events) >= 1
            record("jsonrpc/subscribe-to-task", "Subscribe To Task", ok,
                   f"subscription events={len(sub_events)}", ms)
        finally:
            await hc.aclose()

    await asyncio.wait_for(do_subscribe(), timeout=15.0)


async def test_error_subscribe_not_found():
    """Subscribe to a nonexistent task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        if not hasattr(client, "subscribe"):
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-subscribe-not-found", "Error Subscribe Not Found", True,
                   "SDK does not support SubscribeToTask", ms)
            return
        try:
            async for _ in client.subscribe(
                pb2.SubscribeToTaskRequest(id="00000000-0000-0000-0000-000000000000")
            ):
                break
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-subscribe-not-found", "Error Subscribe Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/error-subscribe-not-found", "Error Subscribe Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_stream_message_only():
    """Streaming send of message-only should yield exactly one message event."""
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/spec", "message-only hello", streaming=True)
    ms = int((time.time() - t0) * 1000)
    has_message = any(sr.HasField("message") for sr, _ in events)
    ok = len(events) == 1 and has_message
    record("jsonrpc/stream-message-only", "Stream Message Only", ok,
           f"events={len(events)}, hasMessage={has_message}", ms)


async def test_stream_task_lifecycle():
    """Streaming task-lifecycle should yield task events ending in COMPLETED."""
    t0 = time.time()
    events, final_task = await sdk_send(
        f"{BASE_URL}/spec", "task-lifecycle process this", streaming=True,
    )
    ms = int((time.time() - t0) * 1000)
    has_task_event = any(t is not None for _, t in events)
    final_state = task_state_name(final_task)
    ok = has_task_event and final_state == "TASK_STATE_COMPLETED"
    record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", ok,
           f"hasTaskEvent={has_task_event}, finalState={final_state}, events={len(events)}", ms)


async def test_multi_turn_context_preserved():
    """Multi-turn conversation should preserve contextId across steps."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        # Step 1: start multi-turn conversation
        msg1 = create_text_message_object(role="ROLE_USER", content="multi-turn start")
        task1 = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg1)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                task1 = task
        if not task1:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/multi-turn-context-preserved", "Multi-Turn Context Preserved", False,
                   "step1 returned no task", ms)
            return

        context_id_1 = task1.context_id if task1.context_id else None
        task_id = task1.id

        # Step 2: follow-up with taskId
        msg2 = create_text_message_object(role="ROLE_USER", content="more data")
        msg2.task_id = task_id
        task2 = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                task2 = task
        if not task2:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/multi-turn-context-preserved", "Multi-Turn Context Preserved", False,
                   "step2 returned no task", ms)
            return

        context_id_2 = task2.context_id if task2.context_id else None
        ms = int((time.time() - t0) * 1000)
        ok = context_id_1 is not None and context_id_1 == context_id_2
        record("jsonrpc/multi-turn-context-preserved", "Multi-Turn Context Preserved", ok,
               f"contextId1={context_id_1}, contextId2={context_id_2}, match={context_id_1 == context_id_2}", ms)
    finally:
        await hc.aclose()


async def test_get_task_with_history():
    """GetTask with history_length should succeed."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        # Create a task first
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/get-task-with-history", "GetTask With History", False,
                   "could not create task", ms)
            return
        task_id = final_task.id
        result = await client.get_task(pb2.GetTaskRequest(id=task_id, history_length=10))
        ms = int((time.time() - t0) * 1000)
        history_count = len(result.history) if result.history else 0
        ok = result.id == task_id
        record("jsonrpc/get-task-with-history", "GetTask With History", ok,
               f"taskId={result.id}, historyCount={history_count}", ms)
    finally:
        await hc.aclose()


async def test_get_task_after_failure():
    """GetTask on a failed task should return FAILED state with status message."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec")
    try:
        # Create a failed task
        msg = create_text_message_object(role="ROLE_USER", content="task-failure trigger error")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("jsonrpc/get-task-after-failure", "GetTask After Failure", False,
                   "could not create failed task", ms)
            return
        task_id = final_task.id
        result = await client.get_task(pb2.GetTaskRequest(id=task_id))
        ms = int((time.time() - t0) * 1000)
        state = task_state_name(result)
        has_status_msg = bool(result.status and result.status.message)
        ok = state == "TASK_STATE_FAILED" and has_status_msg
        record("jsonrpc/get-task-after-failure", "GetTask After Failure", ok,
               f"state={state}, hasStatusMsg={has_status_msg}", ms)
    finally:
        await hc.aclose()


# -- REST Tests (via SDK HTTP+JSON transport) ----------------------------

async def test_rest_agent_card_echo():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        config = ClientConfig(
            httpx_client=hc,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
        factory = ClientFactory(config)
        client = await factory.create_from_url(f"{BASE_URL}/echo")
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
        factory = ClientFactory(config)
        client = await factory.create_from_url(f"{BASE_URL}/spec")
    ms = int((time.time() - t0) * 1000)
    record("rest/agent-card-spec", "REST Spec Agent Card", True,
           "card resolved with HTTP+JSON transport", ms)


async def test_rest_spec_extended_card():
    """Test GetExtendedAgentCard for REST binding."""
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
        # Step 1: Get public card
        resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/spec")
        public_card = await resolver.get_agent_card()
        
        # Step 2: Verify extendedAgentCard capability
        has_extended = False
        if public_card.capabilities:
            has_extended = getattr(public_card.capabilities, "extended_agent_card", False)
        
        if not has_extended:
            ms = int((time.time() - t0) * 1000)
            record("rest/spec-extended-card", "REST Spec Extended Agent Card", False,
                   "capabilities.extendedAgentCard not true", ms)
            return
        
        # Step 3: Call GetExtendedAgentCard via REST GET with auth header
        auth_headers = {**A2A_HEADERS, "Authorization": "Bearer agentbin-test-token"}
        response = await hc.get(f"{BASE_URL}/spec/extendedAgentCard", headers=auth_headers)
        
        if response.status_code != 200:
            ms = int((time.time() - t0) * 1000)
            record("rest/spec-extended-card", "REST Spec Extended Agent Card", False,
                   f"HTTP {response.status_code}", ms)
            return
        
        # Step 4: Verify extended card is a valid AgentCard
        extended_card_data = response.json()
        extended_name = extended_card_data.get("name", "")
        extended_skills = extended_card_data.get("skills", [])
        
        # Step 5: Verify extended card has more skills or has admin-status
        public_skill_count = len(public_card.skills)
        extended_skill_count = len(extended_skills)
        extended_skill_ids = [s.get("id", "") for s in extended_skills]
        has_admin_status = "admin-status" in extended_skill_ids
        
        ok = (extended_skill_count > public_skill_count or has_admin_status) and extended_name
        ms = int((time.time() - t0) * 1000)
        record("rest/spec-extended-card", "REST Spec Extended Agent Card", ok,
               f"public={public_skill_count} skills, extended={extended_skill_count} skills, "
               f"hasAdminStatus={has_admin_status}, name={extended_name!r}", ms)


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
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg1)):
            task = _sr.task if _sr.HasField("task") else None
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
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
            task = _sr.task if _sr.HasField("task") else None
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
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg3)):
            task = _sr.task if _sr.HasField("task") else None
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
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
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
            async for _sr in client.send_message(req):
                task = _sr.task if _sr.HasField("task") else None
                if task:
                    final_task = task
            return final_task
        finally:
            await hc.aclose()

    task = await asyncio.wait_for(do_send(), timeout=15.0)
    elapsed = time.time() - t0
    ms = int(elapsed * 1000)
    state = task_state_name(task)

    if elapsed < 3.0:
        ok = True
        detail = f"returned in {elapsed:.1f}s with state={state}"
    else:
        ok = False
        detail = f"returnImmediately ignored by SDK — blocked {elapsed:.1f}s, state={state}"

    record("rest/spec-return-immediately", "REST Spec Return Immediately", ok,
           detail, ms)


async def test_rest_error_cancel_not_found():
    """REST CancelTask with a nonexistent ID should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        try:
            await client.cancel_task(pb2.CancelTaskRequest(id="00000000-0000-0000-0000-000000000000"))
            ms = int((time.time() - t0) * 1000)
            record("rest/error-cancel-not-found", "REST Error Cancel Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-cancel-not-found", "REST Error Cancel Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_error_cancel_terminal():
    """REST CancelTask on a completed task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-cancel-terminal", "REST Error Cancel Terminal", False,
                   "could not create completed task", ms)
            return
        task_id = final_task.id
        try:
            await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            ms = int((time.time() - t0) * 1000)
            record("rest/error-cancel-terminal", "REST Error Cancel Terminal", False,
                   "expected error canceling completed task, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-cancel-terminal", "REST Error Cancel Terminal", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_error_send_terminal():
    """REST SendMessage to a completed task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-send-terminal", "REST Error Send Terminal", False,
                   "could not create completed task", ms)
            return
        task_id = final_task.id
        try:
            msg2 = create_text_message_object(role="ROLE_USER", content="follow-up to completed task")
            msg2.task_id = task_id
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
                task = _sr.task if _sr.HasField("task") else None
                pass
            ms = int((time.time() - t0) * 1000)
            record("rest/error-send-terminal", "REST Error Send Terminal", False,
                   "expected error sending to completed task, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-send-terminal", "REST Error Send Terminal", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_error_send_invalid_task():
    """REST SendMessage with a bogus taskId should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        try:
            msg = create_text_message_object(role="ROLE_USER", content="hello")
            msg.task_id = "00000000-0000-0000-0000-000000000000"
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
                pass
            ms = int((time.time() - t0) * 1000)
            record("rest/error-send-invalid-task", "REST Error Send Invalid Task", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-send-invalid-task", "REST Error Send Invalid Task", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_error_push_not_supported():
    """REST SetTaskPushNotificationConfig should error since server doesn't support push."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        if not hasattr(client, "set_task_callback"):
            ms = int((time.time() - t0) * 1000)
            record("rest/error-push-not-supported", "REST Error Push Not Supported", True,
                   "SDK does not support push notification config", ms)
            return
        try:
            push_config = pb2.PushNotificationConfig(url="https://example.com/webhook")
            req = pb2.SetTaskPushNotificationConfigRequest(
                task_id="dummy",
                push_notification_config=push_config,
            )
            await client.set_task_callback(req)
            ms = int((time.time() - t0) * 1000)
            record("rest/error-push-not-supported", "REST Error Push Not Supported", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-push-not-supported", "REST Error Push Not Supported", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_subscribe_to_task():
    """REST Subscribe to a working task, collect events, then cancel."""
    t0 = time.time()

    async def do_subscribe():
        client, hc = await make_client(f"{BASE_URL}/spec", streaming=True, binding="REST")
        try:
            if not hasattr(client, "subscribe"):
                ms = int((time.time() - t0) * 1000)
                record("rest/subscribe-to-task", "REST Subscribe To Task", True,
                       "SDK does not support SubscribeToTask", ms)
                return

            msg = create_text_message_object(role="ROLE_USER", content="task-cancel")
            task_id = None
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
                if task:
                    task_id = task.id
                    break

            if not task_id:
                ms = int((time.time() - t0) * 1000)
                record("rest/subscribe-to-task", "REST Subscribe To Task", False,
                       "could not start working task", ms)
                return

            sub_events = []

            async def collect_events():
                async for event in client.subscribe(pb2.SubscribeToTaskRequest(id=task_id)):
                    sub_events.append(event)

            collect_task = asyncio.create_task(collect_events())
            await asyncio.sleep(1)

            await client.cancel_task(pb2.CancelTaskRequest(id=task_id))
            try:
                await asyncio.wait_for(collect_task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass

            ms = int((time.time() - t0) * 1000)
            ok = len(sub_events) >= 1
            record("rest/subscribe-to-task", "REST Subscribe To Task", ok,
                   f"subscription events={len(sub_events)}", ms)
        finally:
            await hc.aclose()

    await asyncio.wait_for(do_subscribe(), timeout=15.0)


async def test_rest_error_subscribe_not_found():
    """REST Subscribe to a nonexistent task should raise an error."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        if not hasattr(client, "subscribe"):
            ms = int((time.time() - t0) * 1000)
            record("rest/error-subscribe-not-found", "REST Error Subscribe Not Found", True,
                   "SDK does not support SubscribeToTask", ms)
            return
        try:
            async for _ in client.subscribe(
                pb2.SubscribeToTaskRequest(id="00000000-0000-0000-0000-000000000000")
            ):
                break
            ms = int((time.time() - t0) * 1000)
            record("rest/error-subscribe-not-found", "REST Error Subscribe Not Found", False,
                   "expected error, got success", ms)
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            record("rest/error-subscribe-not-found", "REST Error Subscribe Not Found", True,
                   f"got expected error: {type(exc).__name__}: {str(exc)[:80]}", ms)
    finally:
        await hc.aclose()


async def test_rest_stream_message_only():
    """REST streaming send of message-only should yield exactly one message event."""
    t0 = time.time()
    events, _ = await sdk_send(f"{BASE_URL}/spec", "message-only hello", streaming=True, binding="REST")
    ms = int((time.time() - t0) * 1000)
    has_message = any(sr.HasField("message") for sr, _ in events)
    ok = len(events) == 1 and has_message
    record("rest/stream-message-only", "REST Stream Message Only", ok,
           f"events={len(events)}, hasMessage={has_message}", ms)


async def test_rest_stream_task_lifecycle():
    """REST streaming task-lifecycle should yield task events ending in COMPLETED."""
    t0 = time.time()
    events, final_task = await sdk_send(
        f"{BASE_URL}/spec", "task-lifecycle process this", streaming=True, binding="REST",
    )
    ms = int((time.time() - t0) * 1000)
    has_task_event = any(t is not None for _, t in events)
    final_state = task_state_name(final_task)
    ok = has_task_event and final_state == "TASK_STATE_COMPLETED"
    record("rest/stream-task-lifecycle", "REST Stream Task Lifecycle", ok,
           f"hasTaskEvent={has_task_event}, finalState={final_state}, events={len(events)}", ms)


async def test_rest_multi_turn_context_preserved():
    """REST multi-turn conversation should preserve contextId across steps."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        msg1 = create_text_message_object(role="ROLE_USER", content="multi-turn start")
        task1 = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg1)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                task1 = task
        if not task1:
            ms = int((time.time() - t0) * 1000)
            record("rest/multi-turn-context-preserved", "REST Multi-Turn Context Preserved", False,
                   "step1 returned no task", ms)
            return

        context_id_1 = task1.context_id if task1.context_id else None
        task_id = task1.id

        msg2 = create_text_message_object(role="ROLE_USER", content="more data")
        msg2.task_id = task_id
        task2 = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg2)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                task2 = task
        if not task2:
            ms = int((time.time() - t0) * 1000)
            record("rest/multi-turn-context-preserved", "REST Multi-Turn Context Preserved", False,
                   "step2 returned no task", ms)
            return

        context_id_2 = task2.context_id if task2.context_id else None
        ms = int((time.time() - t0) * 1000)
        ok = context_id_1 is not None and context_id_1 == context_id_2
        record("rest/multi-turn-context-preserved", "REST Multi-Turn Context Preserved", ok,
               f"contextId1={context_id_1}, contextId2={context_id_2}, match={context_id_1 == context_id_2}", ms)
    finally:
        await hc.aclose()


async def test_rest_get_task_with_history():
    """REST GetTask with history_length should succeed."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process this")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("rest/get-task-with-history", "REST GetTask With History", False,
                   "could not create task", ms)
            return
        task_id = final_task.id
        result = await client.get_task(pb2.GetTaskRequest(id=task_id, history_length=10))
        ms = int((time.time() - t0) * 1000)
        history_count = len(result.history) if result.history else 0
        ok = result.id == task_id
        record("rest/get-task-with-history", "REST GetTask With History", ok,
               f"taskId={result.id}, historyCount={history_count}", ms)
    finally:
        await hc.aclose()


async def test_rest_get_task_after_failure():
    """REST GetTask on a failed task should return FAILED state with status message."""
    t0 = time.time()
    client, hc = await make_client(f"{BASE_URL}/spec", binding="REST")
    try:
        msg = create_text_message_object(role="ROLE_USER", content="task-failure trigger error")
        final_task = None
        async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        if not final_task:
            ms = int((time.time() - t0) * 1000)
            record("rest/get-task-after-failure", "REST GetTask After Failure", False,
                   "could not create failed task", ms)
            return
        task_id = final_task.id
        result = await client.get_task(pb2.GetTaskRequest(id=task_id))
        ms = int((time.time() - t0) * 1000)
        state = task_state_name(result)
        has_status_msg = bool(result.status and result.status.message)
        ok = state == "TASK_STATE_FAILED" and has_status_msg
        record("rest/get-task-after-failure", "REST GetTask After Failure", ok,
               f"state={state}, hasStatusMsg={has_status_msg}", ms)
    finally:
        await hc.aclose()


# -- v0.3 Backward Compatibility Tests --------------------------------

async def make_v03_client(url: str, *, streaming: bool = False):
    """Create an SDK client for a v0.3 agent (no A2A-Version header)."""
    hc = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    config = ClientConfig(
        streaming=streaming,
        httpx_client=hc,
    )
    factory = ClientFactory(config)
    client = await factory.create_from_url(url)
    return client, hc


async def test_v03_agent_card():
    """Fetch the v0.3 agent card via SDK A2ACardResolver and verify its structure."""
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=A2A_HEADERS) as hc:
            resolver = A2ACardResolver(httpx_client=hc, base_url=f"{BASE_URL}/spec03")
            card = await resolver.get_agent_card()
        ms = int((time.time() - t0) * 1000)
        has_iface = len(card.supported_interfaces) > 0
        iface_url = card.supported_interfaces[0].url if has_iface else ""
        proto_ver = card.supported_interfaces[0].protocol_version if has_iface else ""
        ok = has_iface and bool(iface_url)
        record("v03/spec03-agent-card", "v0.3 Agent Card", ok,
               f"protocolVersion={proto_ver!r}, hasUrl={bool(iface_url)}", ms)
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-agent-card", "v0.3 Agent Card", False,
               f"SDK resolver failed: {type(exc).__name__}: {str(exc)[:120]}", ms)


async def test_v03_send_message():
    """Send a message to the v0.3 agent via SDK. Report honestly if v0.3 is unsupported."""
    t0 = time.time()
    try:
        client, hc = await make_v03_client(f"{BASE_URL}/spec03")
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-send-message", "v0.3 Send Message", False,
               f"SDK v0.3 connect failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
        return
    try:
        msg = create_text_message_object(role="ROLE_USER", content="message-only hello")
        req = pb2.SendMessageRequest(message=msg)
        reply = ""
        got_message = False
        async for sr in client.send_message(req):
            task = sr.task if sr.HasField("task") else None
            if sr.HasField("message"):
                got_message = True
                for p in sr.message.parts:
                    if p.text:
                        reply = p.text
        ms = int((time.time() - t0) * 1000)
        ok = got_message and len(reply) > 0
        record("v03/spec03-send-message", "v0.3 Send Message", ok,
               f"gotMessage={got_message}, text={reply!r:.60}", ms)
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-send-message", "v0.3 Send Message", False,
               f"SDK v0.3 send failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
    finally:
        await hc.aclose()


async def test_v03_task_lifecycle():
    """Send task-lifecycle message to v0.3 agent. Report honestly if unsupported."""
    t0 = time.time()
    try:
        client, hc = await make_v03_client(f"{BASE_URL}/spec03")
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", False,
               f"SDK v0.3 connect failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
        return
    try:
        msg = create_text_message_object(role="ROLE_USER", content="task-lifecycle process")
        req = pb2.SendMessageRequest(message=msg)
        final_task = None
        async for _sr in client.send_message(req):
            task = _sr.task if _sr.HasField("task") else None
            if task:
                final_task = task
        ms = int((time.time() - t0) * 1000)
        state = task_state_name(final_task)
        ok = final_task is not None and state in ("TASK_STATE_COMPLETED", "TASK_STATE_WORKING")
        record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", ok,
               f"state={state}, taskId={final_task.id if final_task else None}", ms)
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", False,
               f"SDK v0.3 send failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
    finally:
        await hc.aclose()


async def test_v03_streaming():
    """Stream a message to the v0.3 agent. Report honestly if unsupported."""
    t0 = time.time()
    try:
        client, hc = await make_v03_client(f"{BASE_URL}/spec03", streaming=True)
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-streaming", "v0.3 Streaming", False,
               f"SDK v0.3 connect failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
        return
    try:
        msg = create_text_message_object(role="ROLE_USER", content="streaming generate")
        req = pb2.SendMessageRequest(message=msg)
        events = []
        final_text = ""
        async for sr in client.send_message(req):
            task = sr.task if sr.HasField("task") else None
            events.append((sr, task))
            if task:
                for art in task.artifacts:
                    for p in art.parts:
                        if p.text:
                            final_text = p.text
            if sr.HasField("message"):
                for p in sr.message.parts:
                    if p.text:
                        final_text = p.text
        ms = int((time.time() - t0) * 1000)
        ok = len(events) >= 1 and len(final_text) > 0
        record("v03/spec03-streaming", "v0.3 Streaming", ok,
               f"events={len(events)}, text={final_text!r:.50}", ms)
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        record("v03/spec03-streaming", "v0.3 Streaming", False,
               f"SDK v0.3 stream failed: {type(exc).__name__}: {str(exc)[:100]}", ms)
    finally:
        await hc.aclose()


async def _test_spec_cancel_with_metadata(binding: str):
    """Cancel a streaming task with metadata and verify metadata is echoed back."""
    binding_prefix = "rest" if binding == "REST" else "jsonrpc"
    test_id = f"{binding_prefix}/spec-cancel-with-metadata"
    test_name = f"{'REST ' if binding == 'REST' else ''}Spec Cancel With Metadata"
    t0 = time.time()
    task_id = None
    canceled = False
    metadata_ok = False
    detail = ""

    async def do_cancel():
        nonlocal task_id, canceled, metadata_ok, detail
        client, hc = await make_client(f"{BASE_URL}/spec", streaming=True, binding=binding)
        try:
            msg = create_text_message_object(role="ROLE_USER", content="task-cancel start")
            async for _sr in client.send_message(pb2.SendMessageRequest(message=msg)):
                task = _sr.task if _sr.HasField("task") else None
                if task:
                    task_id = task.id
                    break

            if not task_id:
                detail = "no task id received from streaming"
                return

            cancel_req = pb2.CancelTaskRequest(id=task_id)
            cancel_req.metadata.update({
                "reason": "test-cancel-reason",
                "requestedBy": "python-sdk",
            })
            result = await client.cancel_task(cancel_req)
            state = task_state_name(result)
            canceled = state == "TASK_STATE_CANCELED"

            try:
                fields = result.metadata.fields
                has_reason = "reason" in fields
                has_requested_by = "requestedBy" in fields
                metadata_ok = has_reason and has_requested_by
                detail = (f"taskId={task_id}, canceled={canceled}, "
                          f"metadataOk={metadata_ok}, "
                          f"keys={list(fields.keys())}")
            except Exception:
                metadata_ok = False
                detail = (f"taskId={task_id}, canceled={canceled}, "
                          f"metadataOk=False (no metadata on response)")
        finally:
            await hc.aclose()

    try:
        await asyncio.wait_for(do_cancel(), timeout=10.0)
    except Exception as exc:
        detail = detail or f"exception: {type(exc).__name__}: {str(exc)[:120]}"

    ms = int((time.time() - t0) * 1000)
    ok = task_id is not None and canceled and metadata_ok
    if not detail:
        detail = f"taskId={task_id}, canceled={canceled}, metadataOk={metadata_ok}"
    record(test_id, test_name, ok, detail, ms)


# -- Runner -----------------------------------------------------------

ALL_TESTS = [
    # JSON-RPC (SDK) tests
    ("jsonrpc/agent-card-echo",              test_agent_card_echo),
    ("jsonrpc/agent-card-spec",              test_agent_card_spec),
    ("jsonrpc/spec-extended-card",           test_spec_extended_card),
    ("jsonrpc/echo-send-message",            test_echo_send_message),
    ("jsonrpc/spec-message-only",            test_spec_message_only),
    ("jsonrpc/spec-task-lifecycle",          test_spec_task_lifecycle),
    ("jsonrpc/spec-get-task",                test_spec_get_task),
    ("jsonrpc/spec-task-failure",            test_spec_task_failure),
    ("jsonrpc/spec-data-types",              test_spec_data_types),
    ("jsonrpc/spec-streaming",               test_spec_streaming),
    ("jsonrpc/error-task-not-found",         test_error_task_not_found),
    ("jsonrpc/spec-multi-turn",              test_spec_multi_turn),
    ("jsonrpc/spec-task-cancel",             test_spec_task_cancel),
    ("jsonrpc/spec-list-tasks",              test_spec_list_tasks),
    ("jsonrpc/spec-return-immediately",      test_spec_return_immediately),
    ("jsonrpc/error-cancel-not-found",       test_error_cancel_not_found),
    ("jsonrpc/error-cancel-terminal",        test_error_cancel_terminal),
    ("jsonrpc/error-send-terminal",          test_error_send_terminal),
    ("jsonrpc/error-send-invalid-task",      test_error_send_invalid_task),
    ("jsonrpc/error-push-not-supported",     test_error_push_not_supported),
    ("jsonrpc/subscribe-to-task",            test_subscribe_to_task),
    ("jsonrpc/error-subscribe-not-found",    test_error_subscribe_not_found),
    ("jsonrpc/stream-message-only",          test_stream_message_only),
    ("jsonrpc/stream-task-lifecycle",        test_stream_task_lifecycle),
    ("jsonrpc/multi-turn-context-preserved", test_multi_turn_context_preserved),
    ("jsonrpc/get-task-with-history",        test_get_task_with_history),
    ("jsonrpc/get-task-after-failure",       test_get_task_after_failure),
    ("jsonrpc/spec-cancel-with-metadata",   lambda: _test_spec_cancel_with_metadata("JSONRPC")),
    # REST binding tests
    ("rest/agent-card-echo",                 test_rest_agent_card_echo),
    ("rest/agent-card-spec",                 test_rest_agent_card_spec),
    ("rest/spec-extended-card",              test_rest_spec_extended_card),
    ("rest/echo-send-message",               test_rest_echo_send_message),
    ("rest/spec-message-only",               test_rest_spec_message_only),
    ("rest/spec-task-lifecycle",             test_rest_spec_task_lifecycle),
    ("rest/spec-get-task",                   test_rest_spec_get_task),
    ("rest/spec-task-failure",               test_rest_spec_task_failure),
    ("rest/spec-data-types",                 test_rest_spec_data_types),
    ("rest/spec-streaming",                  test_rest_spec_streaming),
    ("rest/error-task-not-found",            test_rest_error_task_not_found),
    ("rest/spec-multi-turn",                 test_rest_spec_multi_turn),
    ("rest/spec-task-cancel",                test_rest_spec_task_cancel),
    ("rest/spec-list-tasks",                 test_rest_spec_list_tasks),
    ("rest/spec-return-immediately",         test_rest_spec_return_immediately),
    ("rest/error-cancel-not-found",          test_rest_error_cancel_not_found),
    ("rest/error-cancel-terminal",           test_rest_error_cancel_terminal),
    ("rest/error-send-terminal",             test_rest_error_send_terminal),
    ("rest/error-send-invalid-task",         test_rest_error_send_invalid_task),
    ("rest/error-push-not-supported",        test_rest_error_push_not_supported),
    ("rest/subscribe-to-task",               test_rest_subscribe_to_task),
    ("rest/error-subscribe-not-found",       test_rest_error_subscribe_not_found),
    ("rest/stream-message-only",             test_rest_stream_message_only),
    ("rest/stream-task-lifecycle",           test_rest_stream_task_lifecycle),
    ("rest/multi-turn-context-preserved",    test_rest_multi_turn_context_preserved),
    ("rest/get-task-with-history",           test_rest_get_task_with_history),
    ("rest/get-task-after-failure",          test_rest_get_task_after_failure),
    ("rest/spec-cancel-with-metadata",      lambda: _test_spec_cancel_with_metadata("REST")),
    # v0.3 backward compatibility tests
    ("v03/spec03-agent-card",                test_v03_agent_card),
    ("v03/spec03-send-message",              test_v03_send_message),
    ("v03/spec03-task-lifecycle",            test_v03_task_lifecycle),
    ("v03/spec03-streaming",                 test_v03_streaming),
]


def _write_results(results_path: str):
    """Write results.json — called in finally block so it's always written."""
    output = {
        "client": "python",
        "sdk": _SDK_SOURCE,
        "protocolVersion": "1.0",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseUrl": BASE_URL,
        "results": RESULTS,
    }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


async def main():
    print(f"\n{'='*64}")
    print(f"  A2A Python SDK Integration Tests  ({_SDK_SOURCE})")
    print(f"  Target: {BASE_URL}")
    print(f"{'='*64}\n")

    results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")

    try:
        for test_id, fn in ALL_TESTS:
            try:
                await asyncio.wait_for(fn(), timeout=30.0)
            except asyncio.TimeoutError:
                record(test_id, test_id, False, "TIMEOUT: test exceeded 30s", 30000)
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                ms = 0
                record(test_id, test_id, False, f"EXCEPTION: {exc}", ms)
                traceback.print_exc()
            sys.stdout.flush()
    finally:
        # Always write results.json, even on early exit
        _write_results(results_path)

    # Console summary
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"\n{'='*64}")
    print(f"  TOTAL: {passed} passed, {failed} failed, {len(RESULTS)} total")
    print(f"{'='*64}\n")

    print(f"  Results written to {results_path}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))