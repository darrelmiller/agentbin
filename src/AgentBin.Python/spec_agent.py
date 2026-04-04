"""SpecAgent executor for AgentBin Python server."""

import asyncio
import uuid
from datetime import datetime, timezone

from google.protobuf import json_format, struct_pb2

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Message, Part, Role, TaskState


class SpecAgent(AgentExecutor):
    """SpecAgent implementing all 8 test skills."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # TCK routes on messageId prefix (tck-*), not on message text
        message_id = context.message.message_id if context.message else ""
        if message_id.startswith("tck-"):
            await self._route_tck(message_id, context, event_queue)
            return

        text = _extract_text(context.message)
        keyword, _ = _split_keyword(text)

        # Check for multi-turn continuation
        if context.current_task and context.current_task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            await self._handle_multi_turn_continuation(context, event_queue)
            return

        if keyword == "message-only":
            await self._handle_message_only(context, event_queue, text)
        elif keyword == "task-lifecycle":
            await self._handle_task_lifecycle(context, event_queue, text)
        elif keyword == "task-failure":
            await self._handle_task_failure(context, event_queue)
        elif keyword == "task-cancel":
            await self._handle_task_cancel(context, event_queue)
        elif keyword == "multi-turn":
            await self._handle_multi_turn(context, event_queue, text)
        elif keyword == "streaming":
            await self._handle_streaming(context, event_queue)
        elif keyword == "long-running":
            await self._handle_long_running(context, event_queue)
        elif keyword == "data-types":
            await self._handle_data_types(context, event_queue, text)
        else:
            await self._handle_help(context, event_queue)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        msg = _agent_message("[task-cancel] Task canceled by client request.", context.task_id, context.context_id)
        await updater.cancel(msg)

    # --- message-only ---
    async def _handle_message_only(self, ctx: RequestContext, eq: EventQueue, text: str) -> None:
        msg = _agent_message(f"[message-only] You said: {text}", ctx.task_id, ctx.context_id)
        await eq.enqueue_event(msg)

    # --- task-lifecycle ---
    async def _handle_task_lifecycle(self, ctx: RequestContext, eq: EventQueue, text: str) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(
            artifact_id="result",
            name="The processed result",
            parts=[Part(text=f"[task-lifecycle] Processed: {text}")]
        )
        await updater.complete()

    # --- task-failure ---
    async def _handle_task_failure(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        fail_msg = _agent_message(
            "[task-failure] Simulated failure: this task was designed to fail for testing purposes.",
            ctx.task_id, ctx.context_id
        )
        await updater.failed(fail_msg)

    # --- task-cancel ---
    async def _handle_task_cancel(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        work_msg = _agent_message("[task-cancel] Working... send a cancel request to this task.", ctx.task_id, ctx.context_id)
        await updater.start_work(work_msg)
        try:
            await asyncio.sleep(30)
            done_msg = _agent_message("[task-cancel] No cancel received within timeout. Completed normally.", ctx.task_id, ctx.context_id)
            await updater.complete(done_msg)
        except asyncio.CancelledError:
            raise

    # --- multi-turn (first turn) ---
    async def _handle_multi_turn(self, ctx: RequestContext, eq: EventQueue, text: str) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.add_artifact(
            artifact_id="turn-1",
            name="turn-1",
            parts=[Part(text=f"[multi-turn] Received initial message: {text}")]
        )
        prompt = _agent_message("[multi-turn] Please send a follow-up message to continue. Say 'done' to complete.", ctx.task_id, ctx.context_id)
        await updater.requires_input(prompt)

    # --- multi-turn continuation ---
    async def _handle_multi_turn_continuation(self, ctx: RequestContext, eq: EventQueue) -> None:
        text = _extract_text(ctx.message)
        is_done = "done" in text.lower()
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.start_work()
        if is_done:
            await updater.add_artifact(
                artifact_id="final",
                name="final",
                parts=[Part(text=f"[multi-turn] Final message received: {text}")]
            )
            done_msg = _agent_message("[multi-turn] Conversation complete. All turns processed successfully.", ctx.task_id, ctx.context_id)
            await updater.complete(done_msg)
        else:
            turn_id = f"turn-{uuid.uuid4().hex[:8]}"
            await updater.add_artifact(
                artifact_id=turn_id,
                name=turn_id,
                parts=[Part(text=f"[multi-turn] Continuation received: {text}")]
            )
            prompt = _agent_message("[multi-turn] Got it. Send another message, or say 'done' to complete.", ctx.task_id, ctx.context_id)
            await updater.requires_input(prompt)

    # --- streaming ---
    async def _handle_streaming(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        start_msg = _agent_message("[streaming] Starting streamed response...", ctx.task_id, ctx.context_id)
        await updater.start_work(start_msg)
        chunks = [
            "[streaming] Chunk 1: Processing your request...",
            "[streaming] Chunk 2: Analyzing input data...",
            "[streaming] Chunk 3: Generating results...",
            "[streaming] Chunk 4: Finalizing output...",
        ]
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(0.5)
            await updater.add_artifact(
                artifact_id="stream-result",
                name="Streamed Result",
                parts=[Part(text=chunk)],
                append=i > 0,
                last_chunk=i == len(chunks) - 1
            )
        done_msg = _agent_message("[streaming] Stream complete. 4 chunks delivered.", ctx.task_id, ctx.context_id)
        await updater.complete(done_msg)

    # --- long-running ---
    async def _handle_long_running(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        for i in range(1, 6):
            status_msg = _agent_message(f"[long-running] Step {i}/5: Processing...", ctx.task_id, ctx.context_id)
            await updater.start_work(status_msg)
            ts = datetime.now(timezone.utc).isoformat()
            await updater.add_artifact(
                artifact_id=f"step-{i}",
                name=f"step-{i}",
                parts=[Part(text=f"[long-running] Step {i} result: completed at {ts}")]
            )
            if i < 5:
                await asyncio.sleep(2)
        done_msg = _agent_message("[long-running] All 5 steps complete.", ctx.task_id, ctx.context_id)
        await updater.complete(done_msg)

    # --- data-types ---
    async def _handle_data_types(self, ctx: RequestContext, eq: EventQueue, text: str) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()

        # 1. Text artifact
        await updater.add_artifact(
            artifact_id="text-artifact",
            name="Text Artifact",
            parts=[Part(text="[data-types] This is a plain text artifact.")],
            metadata={"description": "A simple text artifact"}
        )

        # 2. JSON data artifact (Part.data is google.protobuf.Value)
        data_dict = {
            "type": "test-result",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": text,
            "metrics": {"latencyMs": 42, "tokensProcessed": 7},
        }
        data_value = struct_pb2.Value()
        json_format.ParseDict(data_dict, data_value)
        await updater.add_artifact(
            artifact_id="data-artifact",
            name="Structured Data Artifact",
            parts=[Part(data=data_value)],
            metadata={"description": "A structured JSON data artifact"}
        )

        # 3. File artifact (SVG as bytes)
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="#4CAF50"/><text x="50" y="55" text-anchor="middle" fill="white" font-size="14">A2A</text></svg>'
        svg_bytes = svg_content.encode("utf-8")
        await updater.add_artifact(
            artifact_id="file-artifact",
            name="File Artifact",
            parts=[Part(raw=svg_bytes, media_type="image/svg+xml", filename="test.svg")],
            metadata={"description": "A binary file artifact (SVG image)"}
        )

        # 4. Multi-part artifact
        multi_value = struct_pb2.Value()
        json_format.ParseDict({"multiPart": True, "partCount": 2}, multi_value)
        await updater.add_artifact(
            artifact_id="multi-part-artifact",
            name="Multi-Part Artifact",
            parts=[
                Part(text="[data-types] This artifact has multiple parts."),
                Part(data=multi_value),
            ],
            metadata={"description": "An artifact containing both text and structured data parts"}
        )

        done_msg = _agent_message(
            "[data-types] Generated 4 artifacts with different content types: text, JSON data, file (SVG), and multi-part.",
            ctx.task_id, ctx.context_id
        )
        await updater.complete(done_msg)

    # --- TCK routing ---
    async def _route_tck(self, message_id: str, ctx: RequestContext, eq: EventQueue) -> None:
        prefix = _extract_tck_prefix(message_id)
        handlers = {
            "complete-task": self._tck_complete_task,
            "artifact-text": self._tck_artifact_text,
            "artifact-file": self._tck_artifact_file,
            "artifact-file-url": self._tck_artifact_file_url,
            "artifact-data": self._tck_artifact_data,
            "message-response": self._tck_message_response,
            "input-required": self._tck_input_required,
            "reject-task": self._tck_reject_task,
            "stream-001": self._tck_stream_basic,
            "stream-002": self._tck_stream_message_only,
            "stream-003": self._tck_stream_task_lifecycle,
            "stream-ordering-001": self._tck_stream_ordering,
            "stream-artifact-text": self._tck_stream_artifact_text,
            "stream-artifact-file": self._tck_stream_artifact_file,
            "stream-artifact-chunked": self._tck_stream_artifact_chunked,
        }
        handler = handlers.get(prefix)
        if handler:
            await handler(ctx, eq)
        else:
            await self._handle_help(ctx, eq)

    # --- TCK core handlers ---
    async def _tck_complete_task(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        msg = _agent_message("Hello from TCK", ctx.task_id, ctx.context_id)
        await updater.complete(msg)

    async def _tck_artifact_text(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="text-artifact", name="text-artifact",
            parts=[Part(text="Generated text content")])
        await updater.complete()

    async def _tck_artifact_file(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="file-artifact", name="file-artifact",
            parts=[Part(raw=b"file content", media_type="text/plain", filename="output.txt")])
        await updater.complete()

    async def _tck_artifact_file_url(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="file-url-artifact", name="file-url-artifact",
            parts=[Part(url="https://example.com/output.txt", media_type="text/plain", filename="output.txt")])
        await updater.complete()

    async def _tck_artifact_data(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        data_value = struct_pb2.Value()
        json_format.ParseDict({"key": "value", "count": 42}, data_value)
        await updater.add_artifact(artifact_id="data-artifact", name="data-artifact",
            parts=[Part(data=data_value)])
        await updater.complete()

    async def _tck_message_response(self, ctx: RequestContext, eq: EventQueue) -> None:
        msg = _agent_message("Direct message response", ctx.task_id, ctx.context_id)
        await eq.enqueue_event(msg)

    async def _tck_input_required(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        msg = _agent_message("Input required \u2014 send a follow-up message.", ctx.task_id, ctx.context_id)
        await updater.requires_input(msg)

    async def _tck_reject_task(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        msg = _agent_message("rejected", ctx.task_id, ctx.context_id)
        await updater.failed(msg)

    # --- TCK streaming handlers ---
    async def _tck_stream_basic(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="stream-artifact", name="stream-artifact",
            parts=[Part(text="Stream hello from TCK")])
        await updater.complete()

    async def _tck_stream_message_only(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.complete()

    async def _tck_stream_task_lifecycle(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="stream-artifact", name="stream-artifact",
            parts=[Part(text="Stream task lifecycle")])
        await updater.complete()

    async def _tck_stream_ordering(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="stream-artifact", name="stream-artifact",
            parts=[Part(text="Ordered output")])
        await updater.complete()

    async def _tck_stream_artifact_text(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="stream-text-artifact", name="stream-text-artifact",
            parts=[Part(text="Streamed text content")])
        await updater.complete()

    async def _tck_stream_artifact_file(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="stream-file-artifact", name="stream-file-artifact",
            parts=[Part(raw=b"file content", media_type="text/plain", filename="output.txt")])
        await updater.complete()

    async def _tck_stream_artifact_chunked(self, ctx: RequestContext, eq: EventQueue) -> None:
        updater = TaskUpdater(eq, ctx.task_id, ctx.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact(artifact_id="chunked-artifact", name="Chunked Artifact",
            parts=[Part(text="chunk-1 ")], last_chunk=False)
        await updater.add_artifact(artifact_id="chunked-artifact", name="Chunked Artifact",
            parts=[Part(text="chunk-2")], append=True, last_chunk=True)
        await updater.complete()

    # --- help ---
    async def _handle_help(self, ctx: RequestContext, eq: EventQueue) -> None:
        help_text = """AgentBin Spec Agent - A2A v1.0 Test Bed

Send a message starting with one of these skill keywords:

  message-only    - Stateless message response (no task)
  task-lifecycle  - Full task: submitted -> working -> completed
  task-failure    - Task that fails with error message
  task-cancel     - Task that waits to be canceled
  multi-turn      - Multi-turn conversation (input-required)
  streaming       - Streamed response with multiple chunks
  long-running    - Long-running task with periodic updates
  data-types      - Mixed content: text, JSON, file, multi-part

Example: "task-lifecycle hello world" """
        await eq.enqueue_event(_agent_message(help_text, ctx.task_id, ctx.context_id))


# --- Module-level helpers ---

def _agent_message(text: str, task_id: str, context_id: str) -> Message:
    return Message(
        role=Role.ROLE_AGENT,
        message_id=str(uuid.uuid4()),
        task_id=task_id,
        context_id=context_id,
        parts=[Part(text=text)],
    )


def _extract_text(message) -> str:
    if not message or not message.parts:
        return ""
    for part in message.parts:
        if part.HasField("text"):
            return part.text
    return ""


def _split_keyword(text: str) -> tuple:
    text = text.strip().lower()
    parts = text.split(None, 1)
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def _extract_tck_prefix(message_id: str) -> str:
    """Extract the TCK prefix from a message ID like 'tck-{prefix}-{session_hex}'."""
    without_prefix = message_id[4:]  # strip "tck-"
    last_dash = without_prefix.rfind("-")
    return without_prefix[:last_dash] if last_dash > 0 else without_prefix
