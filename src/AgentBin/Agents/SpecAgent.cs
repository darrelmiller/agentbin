using System.Text.Json;
using A2A;
using A2A.AspNetCore;

namespace AgentBin.Agents;

/// <summary>
/// Multi-skill A2A spec compliance agent. Routes to different test scenarios
/// based on the skill keyword in the message text. Exercises all A2A v1.0
/// interaction patterns so that client implementers can validate their integrations.
/// </summary>
public sealed class SpecAgent : IAgentHandler
{
    /// <summary>
    /// Override cancel to echo back any metadata the client sent with the cancel request.
    /// This lets interop tests verify that cancel metadata round-trips correctly.
    /// </summary>
    public async Task CancelAsync(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        // Build the canceled task with metadata echoed from the cancel request
        var task = context.Task ?? new AgentTask { Id = context.TaskId, ContextId = context.ContextId };
        task.Status = new A2A.TaskStatus
        {
            State = TaskState.Canceled,
            Timestamp = DateTimeOffset.UtcNow,
        };

        if (context.Metadata is { Count: > 0 })
        {
            task.Metadata ??= new Dictionary<string, JsonElement>();
            foreach (var kvp in context.Metadata)
            {
                task.Metadata[kvp.Key] = kvp.Value;
            }
        }

        // Emit the full task object — bypasses TaskUpdater status-only path
        await eventQueue.EnqueueTaskAsync(task, ct);
        eventQueue.Complete();
    }

    public async Task ExecuteAsync(RequestContext context, AgentEventQueue eventQueue, CancellationToken cancellationToken)
    {
        // Continuations (follow-up messages with taskId) go straight to the
        // handler that owns the task — the user text won't have a skill prefix.
        if (context.IsContinuation)
        {
            await HandleMultiTurn(context, eventQueue, cancellationToken);
            return;
        }

        // TCK routes on messageId prefix (tck-*), not on message text.
        var messageId = context.Message.MessageId ?? "";
        if (TryRouteTck(messageId, out var tckHandler))
        {
            await tckHandler(context, eventQueue, cancellationToken);
            return;
        }

        var text = context.UserText?.Trim().ToLowerInvariant() ?? "";

        // Route to the appropriate skill based on message text
        var skill = text switch
        {
            _ when text.StartsWith("message-only") => "message-only",
            _ when text.StartsWith("task-lifecycle") => "task-lifecycle",
            _ when text.StartsWith("task-failure") => "task-failure",
            _ when text.StartsWith("task-cancel") => "task-cancel",
            _ when text.StartsWith("multi-turn") => "multi-turn",
            _ when text.StartsWith("streaming") => "streaming",
            _ when text.StartsWith("long-running") => "long-running",
            _ when text.StartsWith("data-types") => "data-types",
            _ => "help",
        };

        switch (skill)
        {
            case "message-only":
                await HandleMessageOnly(context, eventQueue, cancellationToken);
                break;
            case "task-lifecycle":
                await HandleTaskLifecycle(context, eventQueue, cancellationToken);
                break;
            case "task-failure":
                await HandleTaskFailure(context, eventQueue, cancellationToken);
                break;
            case "task-cancel":
                await HandleTaskCancel(context, eventQueue, cancellationToken);
                break;
            case "multi-turn":
                await HandleMultiTurn(context, eventQueue, cancellationToken);
                break;
            case "streaming":
                await HandleStreaming(context, eventQueue, cancellationToken);
                break;
            case "long-running":
                await HandleLongRunning(context, eventQueue, cancellationToken);
                break;
            case "data-types":
                await HandleDataTypes(context, eventQueue, cancellationToken);
                break;
            default:
                await HandleHelp(context, eventQueue, cancellationToken);
                break;
        }
    }

    /// <summary>
    /// Stateless message send/receive — no task created.
    /// Tests: message/send returning a Message (not a Task).
    /// </summary>
    private static async Task HandleMessageOnly(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var responder = new MessageResponder(eventQueue, context.ContextId);
        await responder.ReplyAsync($"[message-only] You said: {context.UserText}", ct);
    }

    /// <summary>
    /// Full task state machine: submitted → working → completed with artifact.
    /// Tests: task creation, state transitions, artifact generation.
    /// </summary>
    private static async Task HandleTaskLifecycle(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);

        await updater.AddArtifactAsync(
            [Part.FromText($"[task-lifecycle] Processed: {context.UserText}")],
            name: "result",
            description: "The processed result",
            cancellationToken: ct);

        await updater.CompleteAsync(cancellationToken: ct);
    }

    /// <summary>
    /// Task that transitions to failed state with an error message.
    /// Tests: task failure handling, error messages in status.
    /// </summary>
    private static async Task HandleTaskFailure(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);

        await updater.FailAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("[task-failure] Simulated failure: this task was designed to fail for testing purposes.")],
            },
            ct);
    }

    /// <summary>
    /// Task that stays in working state long enough to be canceled.
    /// Tests: tasks/cancel, CancelAsync on the agent handler.
    /// </summary>
    private static async Task HandleTaskCancel(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("[task-cancel] Working... send a cancel request to this task.")],
            },
            ct);

        // Stay in working state — wait for cancellation or timeout
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(30), ct);
            // If we get here, nobody canceled us — complete normally
            await updater.CompleteAsync(
                new Message
                {
                    Role = Role.Agent,
                    MessageId = Guid.NewGuid().ToString("N"),
                    Parts = [Part.FromText("[task-cancel] No cancel received within timeout. Completed normally.")],
                },
                ct);
        }
        catch (OperationCanceledException)
        {
            // Cancellation was requested — the default CancelAsync on IAgentHandler will handle the state transition
        }
    }

    /// <summary>
    /// Multi-turn interaction: input-required → client sends more input → completed.
    /// Tests: InputRequired state, task continuation, IsContinuation flag, history accumulation.
    /// </summary>
    private static async Task HandleMultiTurn(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        if (!context.IsContinuation)
        {
            // First turn: acknowledge and ask for more input
            await updater.SubmitAsync(ct);
            await updater.AddArtifactAsync(
                [Part.FromText($"[multi-turn] Received initial message: {context.UserText}")],
                name: "turn-1",
                cancellationToken: ct);

            await updater.RequireInputAsync(
                new Message
                {
                    Role = Role.Agent,
                    MessageId = Guid.NewGuid().ToString("N"),
                    ContextId = context.ContextId,
                    Parts = [Part.FromText("[multi-turn] Please send a follow-up message to continue. Say 'done' to complete.")],
                },
                ct);
            return;
        }

        // Continuation turn — re-emit the task to start a new response, then transition
        await updater.SubmitAsync(ct);
        var userText = context.UserText?.Trim().ToLowerInvariant() ?? "";
        if (userText.Contains("done"))
        {
            await updater.StartWorkAsync(cancellationToken: ct);
            await updater.AddArtifactAsync(
                [Part.FromText($"[multi-turn] Final message received: {context.UserText}")],
                name: "final",
                cancellationToken: ct);
            await updater.CompleteAsync(
                new Message
                {
                    Role = Role.Agent,
                    MessageId = Guid.NewGuid().ToString("N"),
                    Parts = [Part.FromText("[multi-turn] Conversation complete. All turns processed successfully.")],
                },
                ct);
        }
        else
        {
            // Not done yet — acknowledge and ask for more input
            await updater.StartWorkAsync(cancellationToken: ct);
            await updater.AddArtifactAsync(
                [Part.FromText($"[multi-turn] Continuation received: {context.UserText}")],
                name: $"turn-{DateTime.UtcNow.Ticks}",
                cancellationToken: ct);

            await updater.RequireInputAsync(
                new Message
                {
                    Role = Role.Agent,
                    MessageId = Guid.NewGuid().ToString("N"),
                    ContextId = context.ContextId,
                    Parts = [Part.FromText("[multi-turn] Got it. Send another message, or say 'done' to complete.")],
                },
                ct);
        }
    }

    /// <summary>
    /// Streams multiple status updates and artifact chunks via SSE.
    /// Tests: message/stream, TaskStatusUpdateEvent, TaskArtifactUpdateEvent, progressive output.
    /// </summary>
    private static async Task HandleStreaming(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("[streaming] Starting streamed response...")],
            },
            ct);

        // Stream multiple artifact chunks with delays
        var chunks = new[]
        {
            "Chunk 1: Processing your request...",
            "Chunk 2: Analyzing input data...",
            "Chunk 3: Generating results...",
            "Chunk 4: Finalizing output...",
        };

        for (int i = 0; i < chunks.Length; i++)
        {
            await Task.Delay(500, ct);
            await updater.AddArtifactAsync(
                [Part.FromText($"[streaming] {chunks[i]}")],
                artifactId: "stream-result",
                name: "Streamed Result",
                lastChunk: i == chunks.Length - 1,
                append: i > 0,
                cancellationToken: ct);
        }

        await updater.CompleteAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("[streaming] Stream complete. 4 chunks delivered.")],
            },
            ct);
    }

    /// <summary>
    /// Simulates a long-running task with periodic status updates.
    /// Tests: long-lived tasks, periodic updates, task polling via tasks/get.
    /// </summary>
    private static async Task HandleLongRunning(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);

        var steps = 5;
        for (int i = 1; i <= steps; i++)
        {
            await updater.StartWorkAsync(
                new Message
                {
                    Role = Role.Agent,
                    MessageId = Guid.NewGuid().ToString("N"),
                    Parts = [Part.FromText($"[long-running] Step {i}/{steps}: Processing...")],
                },
                ct);

            await Task.Delay(2000, ct);

            await updater.AddArtifactAsync(
                [Part.FromText($"[long-running] Step {i} result: completed at {DateTimeOffset.UtcNow:O}")],
                name: $"step-{i}",
                cancellationToken: ct);
        }

        await updater.CompleteAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText($"[long-running] All {steps} steps complete.")],
            },
            ct);
    }

    /// <summary>
    /// Returns mixed content types: text, structured data, and file parts.
    /// Tests: Part.FromText, Part.FromData, Part.FromRaw, multiple parts in artifacts.
    /// </summary>
    private static async Task HandleDataTypes(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);

        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);

        // Artifact 1: Text
        await updater.AddArtifactAsync(
            [Part.FromText("[data-types] This is a plain text artifact.")],
            artifactId: "text-artifact",
            name: "Text Artifact",
            description: "A simple text artifact",
            cancellationToken: ct);

        // Artifact 2: Structured JSON data
        var jsonData = JsonSerializer.SerializeToElement(new
        {
            type = "test-result",
            timestamp = DateTimeOffset.UtcNow,
            input = context.UserText,
            metrics = new { latencyMs = 42, tokensProcessed = 7 }
        });
        await updater.AddArtifactAsync(
            [Part.FromData(jsonData)],
            artifactId: "data-artifact",
            name: "Structured Data Artifact",
            description: "A structured JSON data artifact",
            cancellationToken: ct);

        // Artifact 3: File content (small SVG image)
        var svgContent = """
            <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
              <circle cx="50" cy="50" r="40" fill="#4CAF50"/>
              <text x="50" y="55" text-anchor="middle" fill="white" font-size="14">A2A</text>
            </svg>
            """;
        await updater.AddArtifactAsync(
            [Part.FromRaw(System.Text.Encoding.UTF8.GetBytes(svgContent), mediaType: "image/svg+xml", filename: "test.svg")],
            artifactId: "file-artifact",
            name: "File Artifact",
            description: "A binary file artifact (SVG image)",
            cancellationToken: ct);

        // Artifact 4: Multi-part artifact (text + data combined)
        await updater.AddArtifactAsync(
            [
                Part.FromText("[data-types] This artifact has multiple parts."),
                Part.FromData(JsonSerializer.SerializeToElement(new { multiPart = true, partCount = 2 })),
            ],
            artifactId: "multi-part-artifact",
            name: "Multi-Part Artifact",
            description: "An artifact containing both text and structured data parts",
            cancellationToken: ct);

        await updater.CompleteAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("[data-types] Generated 4 artifacts with different content types: text, JSON data, file (SVG), and multi-part.")],
            },
            ct);
    }

    // ────────────────────────────────────────────────────────────────────────
    // TCK (Test Compatibility Kit) support
    //
    // The A2A TCK routes on messageId prefix (tck-*), not on message text.
    // Each prefix maps to a Gherkin scenario in scenarios/core_operations.feature
    // and scenarios/streaming.feature.
    // ────────────────────────────────────────────────────────────────────────

    private delegate Task TckHandlerDelegate(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct);

    private static bool TryRouteTck(string messageId, [System.Diagnostics.CodeAnalysis.NotNullWhen(true)] out TckHandlerDelegate? handler)
    {
        // TCK messageIds are formatted as "tck-{prefix}-{session_hex}"
        if (!messageId.StartsWith("tck-", StringComparison.OrdinalIgnoreCase))
        {
            handler = null;
            return false;
        }

        // Strip "tck-" prefix and the trailing session suffix (last segment after final '-')
        // e.g. "tck-complete-task-a1b2c3d4" → "complete-task"
        var withoutPrefix = messageId.Substring(4);
        var lastDash = withoutPrefix.LastIndexOf('-');
        var prefix = lastDash > 0 ? withoutPrefix.Substring(0, lastDash) : withoutPrefix;

        handler = prefix switch
        {
            // Core operations
            "complete-task" => TckCompleteTask,
            "artifact-text" => TckArtifactText,
            "artifact-file" => TckArtifactFile,
            "artifact-file-url" => TckArtifactFileUrl,
            "artifact-data" => TckArtifactData,
            "message-response" => TckMessageResponse,
            "input-required" => TckInputRequired,
            "reject-task" => TckRejectTask,

            // Streaming operations
            "stream-001" => TckStreamBasic,
            "stream-002" => TckStreamMessageOnly,
            "stream-003" => TckStreamTaskLifecycle,
            "stream-ordering-001" => TckStreamOrdering,
            "stream-artifact-text" => TckStreamArtifactText,
            "stream-artifact-file" => TckStreamArtifactFile,
            "stream-artifact-chunked" => TckStreamArtifactChunked,

            _ => null,
        };

        return handler is not null;
    }

    // -- Core TCK scenarios --

    private static async Task TckCompleteTask(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.CompleteAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("Hello from TCK")],
            }, ct);
    }

    private static async Task TckArtifactText(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("Generated text content")],
            name: "text-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckArtifactFile(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromRaw(System.Text.Encoding.UTF8.GetBytes("file content"), mediaType: "text/plain", filename: "output.txt")],
            name: "file-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckArtifactFileUrl(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromUrl("https://example.com/output.txt", mediaType: "text/plain", filename: "output.txt")],
            name: "file-url-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckArtifactData(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromData(JsonSerializer.SerializeToElement(new { key = "value", count = 42 }))],
            name: "data-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckMessageResponse(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var responder = new MessageResponder(eventQueue, context.ContextId);
        await responder.ReplyAsync("Direct message response", ct);
    }

    private static async Task TckInputRequired(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.RequireInputAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("Input required — send a follow-up message.")],
            }, ct);
    }

    private static async Task TckRejectTask(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.FailAsync(
            new Message
            {
                Role = Role.Agent,
                MessageId = Guid.NewGuid().ToString("N"),
                Parts = [Part.FromText("rejected")],
            }, ct);
    }

    // -- Streaming TCK scenarios --

    private static async Task TckStreamBasic(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("Stream hello from TCK")],
            name: "stream-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamMessageOnly(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamTaskLifecycle(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("Stream task lifecycle")],
            name: "stream-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamOrdering(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("Ordered output")],
            name: "stream-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamArtifactText(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("Streamed text content")],
            name: "stream-text-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamArtifactFile(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromRaw(System.Text.Encoding.UTF8.GetBytes("file content"), mediaType: "text/plain", filename: "output.txt")],
            name: "stream-file-artifact",
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    private static async Task TckStreamArtifactChunked(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var updater = new TaskUpdater(eventQueue, context.TaskId, context.ContextId);
        await updater.SubmitAsync(ct);
        await updater.StartWorkAsync(cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("chunk-1 ")],
            artifactId: "chunked-artifact",
            name: "Chunked Artifact",
            lastChunk: false,
            cancellationToken: ct);
        await updater.AddArtifactAsync(
            [Part.FromText("chunk-2")],
            artifactId: "chunked-artifact",
            name: "Chunked Artifact",
            append: true,
            lastChunk: true,
            cancellationToken: ct);
        await updater.CompleteAsync(cancellationToken: ct);
    }

    /// <summary>
    /// Returns help text listing all available skills.
    /// </summary>
    private static async Task HandleHelp(RequestContext context, AgentEventQueue eventQueue, CancellationToken ct)
    {
        var responder = new MessageResponder(eventQueue, context.ContextId);
        await responder.ReplyAsync("""
            AgentBin Spec Agent — A2A v1.0 Test Bed

            Send a message starting with one of these skill keywords:

              message-only    → Stateless message response (no task)
              task-lifecycle  → Full task: submitted → working → completed
              task-failure    → Task that fails with error message
              task-cancel     → Task that waits to be canceled
              multi-turn      → Multi-turn conversation (input-required)
              streaming       → Streamed response with multiple chunks
              long-running    → Long-running task with periodic updates
              data-types      → Mixed content: text, JSON, file, multi-part

            Example: "task-lifecycle hello world"
            """, ct);
    }

    public static AgentCard GetAgentCard(string agentUrl) =>
        new()
        {
            Name = "AgentBin Spec Agent",
            Description = "A2A v1.0 spec compliance test agent. Exercises all interaction patterns for client validation.",
            Version = "1.0.0",
            SupportedInterfaces =
            [
                new AgentInterface
                {
                    Url = agentUrl,
                    ProtocolBinding = "JSONRPC",
                    ProtocolVersion = "1.0",
                    Tenant = "",
                },
                new AgentInterface
                {
                    Url = agentUrl,
                    ProtocolBinding = "HTTP+JSON",
                    ProtocolVersion = "1.0",
                    Tenant = "",
                }
            ],
            DefaultInputModes = ["text/plain"],
            DefaultOutputModes = ["text/plain", "application/json", "image/svg+xml"],
            Capabilities = new AgentCapabilities { Streaming = true, PushNotifications = false, ExtendedAgentCard = false },
            Skills =
            [
                new AgentSkill
                {
                    Id = "message-only",
                    Name = "Message Only",
                    Description = "Stateless message send/receive — no task created.",
                    Tags = ["message", "stateless"],
                    Examples = ["message-only hello world"],
                },
                new AgentSkill
                {
                    Id = "task-lifecycle",
                    Name = "Task Lifecycle",
                    Description = "Full task state machine: submitted → working → completed with artifact.",
                    Tags = ["task", "lifecycle", "artifact"],
                    Examples = ["task-lifecycle process this"],
                },
                new AgentSkill
                {
                    Id = "task-failure",
                    Name = "Task Failure",
                    Description = "Task that transitions to failed state with error message.",
                    Tags = ["task", "failure", "error"],
                    Examples = ["task-failure trigger error"],
                },
                new AgentSkill
                {
                    Id = "task-cancel",
                    Name = "Task Cancel",
                    Description = "Task that stays working and waits to be canceled via tasks/cancel.",
                    Tags = ["task", "cancel"],
                    Examples = ["task-cancel start"],
                },
                new AgentSkill
                {
                    Id = "multi-turn",
                    Name = "Multi-Turn",
                    Description = "Multi-turn conversation using input-required state. Say 'done' to complete.",
                    Tags = ["multi-turn", "input-required", "conversation"],
                    Examples = ["multi-turn start conversation"],
                },
                new AgentSkill
                {
                    Id = "streaming",
                    Name = "Streaming",
                    Description = "Streams multiple status updates and artifact chunks via SSE.",
                    Tags = ["streaming", "sse", "chunks"],
                    Examples = ["streaming generate output"],
                },
                new AgentSkill
                {
                    Id = "long-running",
                    Name = "Long Running",
                    Description = "Simulates a long-running task with periodic status updates over ~10 seconds.",
                    Tags = ["long-running", "periodic", "polling"],
                    Examples = ["long-running start process"],
                },
                new AgentSkill
                {
                    Id = "data-types",
                    Name = "Data Types",
                    Description = "Returns mixed content: text, structured JSON, file (SVG), and multi-part artifacts.",
                    Tags = ["data-types", "json", "file", "multi-part"],
                    Examples = ["data-types show all"],
                },
            ],
        };

    /// <summary>
    /// Returns a v0.3-format agent card (no supportedInterfaces, has url + protocolVersion).
    /// Used by the /spec03 endpoint to test SDK backward compatibility.
    /// </summary>
    public static object GetV03AgentCard(string agentUrl) => new
    {
        name = "AgentBin Spec Agent (v0.3)",
        description = "A2A v0.3 spec compliance test agent. Tests SDK backward compatibility with v0.3 protocol.",
        version = "1.0.0",
        url = agentUrl,
        protocolVersion = "0.3.0",
        defaultInputModes = new[] { "text/plain" },
        defaultOutputModes = new[] { "text/plain", "application/json", "image/svg+xml" },
        capabilities = new
        {
            supportsStreaming = true,
            supportsPushNotifications = false,
        },
        skills = new[]
        {
            new { id = "message-only", name = "Message Only", description = "Stateless message send/receive.", tags = new[] { "message" }, examples = new[] { "message-only hello" } },
            new { id = "task-lifecycle", name = "Task Lifecycle", description = "Full task state machine.", tags = new[] { "task" }, examples = new[] { "task-lifecycle process" } },
            new { id = "task-failure", name = "Task Failure", description = "Task transitions to failed.", tags = new[] { "task" }, examples = new[] { "task-failure trigger" } },
            new { id = "streaming", name = "Streaming", description = "SSE streaming.", tags = new[] { "streaming" }, examples = new[] { "streaming generate" } },
        },
    };
}
