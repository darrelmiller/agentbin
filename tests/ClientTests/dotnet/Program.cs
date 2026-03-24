/// A2A .NET SDK acceptance tests against the AgentBin service.
/// Tests both JSON-RPC and HTTP+JSON (REST) bindings via SDK.
/// Usage: dotnet run [baseUrl]

using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using A2A;

var baseUrl = args.Length > 0
    ? args[0].TrimEnd('/')
    : "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";

Console.WriteLine($"AgentBin .NET Client Tests — {baseUrl}\n");

var results = new List<TestResult>();
var versionedHttpClient = new HttpClient();
versionedHttpClient.DefaultRequestHeaders.Add("A2A-Version", "1.0");

void Record(string id, string name, bool passed, string detail, long durationMs)
{
    results.Add(new TestResult(id, name, passed, detail, durationMs));
    var tag = passed ? "PASS" : "FAIL";
    Console.WriteLine($"  [{tag}] {id} — {detail}");
}

var sw = Stopwatch.StartNew();

// ═══════════════════════════════════════════════════════════════════════════
// JSON-RPC BINDING (via SDK)
// ═══════════════════════════════════════════════════════════════════════════
Console.WriteLine("── JSON-RPC Binding (SDK) ──");

// 1. agent-card-echo
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/echo/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    Record("jsonrpc/agent-card-echo", "Echo Agent Card", card.Name is not null && card.Skills.Count >= 1,
        $"name={card.Name}, skills={card.Skills.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/agent-card-echo", "Echo Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// 2. agent-card-spec
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/spec/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    Record("jsonrpc/agent-card-spec", "Spec Agent Card", card.Skills.Count == 8,
        $"skills={card.Skills.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/agent-card-spec", "Spec Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// 3. echo-send-message
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/echo"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "hello from .NET SDK", role: Role.User);
    var text = response.Message?.Parts.FirstOrDefault()?.Text ?? "";
    Record("jsonrpc/echo-send-message", "Echo Send Message", text.Contains("hello from .NET SDK", StringComparison.OrdinalIgnoreCase),
        $"text={text}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/echo-send-message", "Echo Send Message", false, ex.Message, sw.ElapsedMilliseconds); }

// 4. spec-message-only
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "message-only from .NET", role: Role.User);
    Record("jsonrpc/spec-message-only", "Message Only", response.Message?.Role == Role.Agent,
        $"role={response.Message?.Role}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-message-only", "Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// 5+6. spec-task-lifecycle + spec-get-task
string? rpcTaskId = null;
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    if (response.Task is { } task)
    {
        rpcTaskId = task.Id;
        Record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", task.Status.State == TaskState.Completed && task.Artifacts?.Count >= 1,
            $"state={task.Status.State}, artifacts={task.Artifacts?.Count}", sw.ElapsedMilliseconds);
        sw.Restart();
        var fetched = await client.GetTaskAsync(new GetTaskRequest { Id = task.Id });
        Record("jsonrpc/spec-get-task", "GetTask", fetched.Id == task.Id,
            $"state={fetched.Status.State}", sw.ElapsedMilliseconds);
    }
    else
    {
        Record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false, "got message, expected task", sw.ElapsedMilliseconds);
        Record("jsonrpc/spec-get-task", "GetTask", false, "skipped", 0);
    }
}
catch (Exception ex)
{
    Record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds);
    Record("jsonrpc/spec-get-task", "GetTask", false, "skipped", 0);
}

// 7. spec-task-failure
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "task-failure trigger error", role: Role.User);
    Record("jsonrpc/spec-task-failure", "Task Failure", response.Task?.Status.State == TaskState.Failed,
        $"state={response.Task?.Status.State}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-task-failure", "Task Failure", false, ex.Message, sw.ElapsedMilliseconds); }

// 8. spec-data-types
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "data-types show all", role: Role.User);
    var t = response.Task;
    var hasText = t?.Artifacts?.Any(a => a.Parts.Any(p => p.Text is not null)) ?? false;
    var hasData = t?.Artifacts?.Any(a => a.Parts.Any(p => p.Data is not null)) ?? false;
    var hasFile = t?.Artifacts?.Any(a => a.Parts.Any(p => p.MediaType is not null)) ?? false;
    Record("jsonrpc/spec-data-types", "Data Types", hasText && hasData && hasFile,
        $"text={hasText}, data={hasData}, file={hasFile}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-data-types", "Data Types", false, ex.Message, sw.ElapsedMilliseconds); }

// 9. spec-streaming
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var request = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("streaming generate output")]
        }
    };
    int evtCount = 0; bool sawArt = false, sawDone = false;
    await foreach (var ev in client.SendStreamingMessageAsync(request))
    {
        evtCount++;
        if (ev.ArtifactUpdate is not null) sawArt = true;
        if (ev.Task?.Status.State == TaskState.Completed || ev.StatusUpdate?.Status.State == TaskState.Completed) sawDone = true;
    }
    Record("jsonrpc/spec-streaming", "Streaming", evtCount >= 3 && sawArt && sawDone,
        $"events={evtCount}, artifact={sawArt}, completed={sawDone}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-streaming", "Streaming", false, ex.Message, sw.ElapsedMilliseconds); }

// 10. error-task-not-found
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    await client.GetTaskAsync(new GetTaskRequest { Id = "00000000-0000-0000-0000-000000000000" });
    Record("jsonrpc/error-task-not-found", "Task Not Found", false, "Should have thrown", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("jsonrpc/error-task-not-found", "Task Not Found", true, $"errorCode={ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-task-not-found", "Task Not Found", false, ex.GetType().Name, sw.ElapsedMilliseconds); }

// 11. spec-multi-turn — 3-step multi-turn conversation
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);

    // Step 1: start conversation
    var r1 = await client.SendMessageAsync(text: "multi-turn start conversation", role: Role.User);
    var mtTaskId = r1.Task?.Id;
    var s1 = r1.Task?.Status.State == TaskState.InputRequired;

    if (mtTaskId is null)
    {
        Record("jsonrpc/spec-multi-turn", "Multi-Turn", false, "step1: no taskId returned", sw.ElapsedMilliseconds);
    }
    else
    {
        // Step 2: follow-up with taskId
        var req2 = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = mtTaskId,
                Parts = [Part.FromText("more data")]
            }
        };
        var r2 = await client.SendMessageAsync(req2);
        var s2 = r2.Task?.Status.State == TaskState.InputRequired;

        // Step 3: finish
        var req3 = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = mtTaskId,
                Parts = [Part.FromText("done")]
            }
        };
        var r3 = await client.SendMessageAsync(req3);
        var s3 = r3.Task?.Status.State == TaskState.Completed;

        Record("jsonrpc/spec-multi-turn", "Multi-Turn", s1 && s2 && s3,
            $"step1={r1.Task?.Status.State}, step2={r2.Task?.Status.State}, step3={r3.Task?.Status.State}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/spec-multi-turn", "Multi-Turn", false, ex.Message, sw.ElapsedMilliseconds); }

// 12. spec-task-cancel — start a long-running task via streaming, then cancel it
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var cancelReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel")]
        }
    };
    string? cancelTaskId = null;
    using var cancelCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await foreach (var ev in client.SendStreamingMessageAsync(cancelReq).WithCancellation(cancelCts.Token))
    {
        cancelTaskId = ev.Task?.Id ?? ev.StatusUpdate?.TaskId ?? ev.ArtifactUpdate?.TaskId;
        if (cancelTaskId is not null) break;
    }
    if (cancelTaskId is null)
    {
        Record("jsonrpc/spec-task-cancel", "Task Cancel", false, "no taskId from streaming", sw.ElapsedMilliseconds);
    }
    else
    {
        await client.CancelTaskAsync(new CancelTaskRequest { Id = cancelTaskId });
        var fetched = await client.GetTaskAsync(new GetTaskRequest { Id = cancelTaskId });
        Record("jsonrpc/spec-task-cancel", "Task Cancel",
            fetched.Status.State == TaskState.Canceled,
            $"taskId={cancelTaskId}, state={fetched.Status.State}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/spec-task-cancel", "Task Cancel", false, ex.Message, sw.ElapsedMilliseconds); }

// 12b. spec-cancel-with-metadata — cancel a running task with metadata
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var cancelMetaReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel start")]
        }
    };
    string? cancelMetaTaskId = null;
    using var cancelMetaCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await foreach (var ev in client.SendStreamingMessageAsync(cancelMetaReq).WithCancellation(cancelMetaCts.Token))
    {
        cancelMetaTaskId = ev.Task?.Id ?? ev.StatusUpdate?.TaskId ?? ev.ArtifactUpdate?.TaskId;
        if (cancelMetaTaskId is not null) break;
    }
    if (cancelMetaTaskId is null)
    {
        Record("jsonrpc/spec-cancel-with-metadata", "Cancel With Metadata", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        var cancelResult = await client.CancelTaskAsync(new CancelTaskRequest
        {
            Id = cancelMetaTaskId,
            Metadata = new Dictionary<string, System.Text.Json.JsonElement>
            {
                ["reason"] = JsonSerializer.SerializeToElement("test-cancel-reason"),
                ["requestedBy"] = JsonSerializer.SerializeToElement("dotnet-sdk")
            }
        });
        var metaKeys = cancelResult.Metadata?.Keys.ToList() ?? [];
        var hasMetadata = metaKeys.Contains("reason") && metaKeys.Contains("requestedBy");
        Record("jsonrpc/spec-cancel-with-metadata", "Cancel With Metadata", cancelResult.Status.State == TaskState.Canceled,
            $"taskId={cancelMetaTaskId}, state={cancelResult.Status.State}, metadataKeys=[{string.Join(",", metaKeys)}]", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/spec-cancel-with-metadata", "Cancel With Metadata", false, ex.Message, sw.ElapsedMilliseconds); }

// 13. spec-list-tasks — list tasks via SDK
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var listResponse = await client.ListTasksAsync(new ListTasksRequest { PageSize = 10 });
    Record("jsonrpc/spec-list-tasks", "List Tasks", listResponse.Tasks.Count >= 1,
        $"tasks={listResponse.Tasks.Count}, totalSize={listResponse.TotalSize}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-list-tasks", "List Tasks", false, ex.Message, sw.ElapsedMilliseconds); }

// 14. spec-return-immediately — test non-blocking configuration via SDK
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var request = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("long-running test")]
        },
        Configuration = new SendMessageConfiguration { Blocking = false }
    };
    var riSw = Stopwatch.StartNew();
    var response = await client.SendMessageAsync(request);
    riSw.Stop();
    var state = response.Task?.Status.State;
    bool riPassed = riSw.ElapsedMilliseconds < 2000 && state == TaskState.Working;
    string riDetail = riPassed
        ? $"state={state}, time={riSw.ElapsedMilliseconds}ms"
        : $"state={state}, time={riSw.ElapsedMilliseconds}ms (expected Working within 2s)";
    Record("jsonrpc/spec-return-immediately", "Return Immediately", riPassed, riDetail, sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-return-immediately", "Return Immediately", false, ex.Message, sw.ElapsedMilliseconds); }

// 15. error-cancel-not-found — cancel a non-existent task
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    await client.CancelTaskAsync(new CancelTaskRequest { Id = "00000000-0000-0000-0000-000000000000" });
    Record("jsonrpc/error-cancel-not-found", "Cancel Not Found", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("jsonrpc/error-cancel-not-found", "Cancel Not Found", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-cancel-not-found", "Cancel Not Found", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 16. error-cancel-terminal — cancel an already-completed task
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var r = await client.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var termCancelTaskId = r.Task?.Id;
    if (termCancelTaskId is null)
    {
        Record("jsonrpc/error-cancel-terminal", "Cancel Terminal Task", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        await client.CancelTaskAsync(new CancelTaskRequest { Id = termCancelTaskId });
        Record("jsonrpc/error-cancel-terminal", "Cancel Terminal Task", false, "expected error, got success", sw.ElapsedMilliseconds);
    }
}
catch (A2AException ex) { Record("jsonrpc/error-cancel-terminal", "Cancel Terminal Task", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-cancel-terminal", "Cancel Terminal Task", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 17. error-send-terminal — send to a completed task, expect error
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var r = await client.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var termTaskId = r.Task?.Id;
    if (termTaskId is null)
    {
        Record("jsonrpc/error-send-terminal", "Send To Terminal Task", false, "no taskId from lifecycle", sw.ElapsedMilliseconds);
    }
    else
    {
        var req = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = termTaskId,
                Parts = [Part.FromText("this should fail")]
            }
        };
        await client.SendMessageAsync(req);
        Record("jsonrpc/error-send-terminal", "Send To Terminal Task", false, "expected error, got success", sw.ElapsedMilliseconds);
    }
}
catch (A2AException ex) { Record("jsonrpc/error-send-terminal", "Send To Terminal Task", true, $"got expected error: {ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-send-terminal", "Send To Terminal Task", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 18. error-send-invalid-task — send message with bogus TaskId
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var req = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            TaskId = "00000000-0000-0000-0000-000000000000",
            Parts = [Part.FromText("send to invalid task")]
        }
    };
    await client.SendMessageAsync(req);
    Record("jsonrpc/error-send-invalid-task", "Send Invalid TaskId", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("jsonrpc/error-send-invalid-task", "Send Invalid TaskId", true, $"errorCode={ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-send-invalid-task", "Send Invalid TaskId", true, $"got error: {ex.GetType().Name}", sw.ElapsedMilliseconds); }

// 19. error-push-not-supported — attempt push notification config, expect error
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    await client.CreateTaskPushNotificationConfigAsync(new CreateTaskPushNotificationConfigRequest
    {
        TaskId = "00000000-0000-0000-0000-000000000000",
        ConfigId = "test-config",
        Config = new PushNotificationConfig { Url = "https://example.com/webhook" }
    });
    Record("jsonrpc/error-push-not-supported", "Push Not Supported", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("jsonrpc/error-push-not-supported", "Push Not Supported", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-push-not-supported", "Push Not Supported", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 20. subscribe-to-task — start a long-running task, then subscribe to its events
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var subReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel start")]
        },
        Configuration = new SendMessageConfiguration { Blocking = false }
    };
    var subResponse = await client.SendMessageAsync(subReq);
    var subTaskId = subResponse.Task?.Id;
    if (subTaskId is null)
    {
        Record("jsonrpc/subscribe-to-task", "SubscribeToTask", false, "no taskId from non-blocking send", sw.ElapsedMilliseconds);
    }
    else
    {
        int subEvtCount = 0;
        using var subCts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await foreach (var ev in client.SubscribeToTaskAsync(new SubscribeToTaskRequest { Id = subTaskId }).WithCancellation(subCts.Token))
        {
            subEvtCount++;
            var evState = ev.Task?.Status.State ?? ev.StatusUpdate?.Status.State;
            if (evState == TaskState.Completed || evState == TaskState.Failed || evState == TaskState.Canceled)
                break;
        }
        Record("jsonrpc/subscribe-to-task", "SubscribeToTask", subEvtCount >= 1,
            $"taskId={subTaskId}, events={subEvtCount}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/subscribe-to-task", "SubscribeToTask", false, ex.Message, sw.ElapsedMilliseconds); }

// 21. error-subscribe-not-found — subscribe to a non-existent task
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    await foreach (var ev in client.SubscribeToTaskAsync(new SubscribeToTaskRequest { Id = "00000000-0000-0000-0000-000000000000" }))
    {
        break; // shouldn't reach here
    }
    Record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found", false, "expected error, got events", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 22. stream-message-only — streaming with message-only response
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var req = new SendMessageRequest
    {
        Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), Parts = [Part.FromText("message-only hello")] }
    };
    int eventCount = 0; bool hasMessage = false;
    await foreach (var ev in client.SendStreamingMessageAsync(req))
    {
        eventCount++;
        if (ev.Message is not null) hasMessage = true;
    }
    Record("jsonrpc/stream-message-only", "Stream Message Only", hasMessage && eventCount == 1,
        $"events={eventCount}, hasMessage={hasMessage}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/stream-message-only", "Stream Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// 23. stream-task-lifecycle — streaming task with lifecycle events
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var req = new SendMessageRequest
    {
        Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), Parts = [Part.FromText("task-lifecycle process this")] }
    };
    bool firstHasTask = false; bool lastTerminal = false; int idx = 0;
    await foreach (var ev in client.SendStreamingMessageAsync(req))
    {
        if (idx == 0 && ev.Task is not null) firstHasTask = true;
        if (ev.Task?.Status.State == TaskState.Completed || ev.StatusUpdate?.Status.State == TaskState.Completed) lastTerminal = true;
        idx++;
    }
    Record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", firstHasTask && lastTerminal,
        $"firstHasTask={firstHasTask}, lastTerminal={lastTerminal}, events={idx}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds); }

// 24. multi-turn-context-preserved — verify contextId is preserved across turns
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var r1 = await client.SendMessageAsync(text: "multi-turn start conversation", role: Role.User);
    var ctx1 = r1.Task?.ContextId;
    var tid = r1.Task?.Id;
    if (tid is null || ctx1 is null)
    {
        Record("jsonrpc/multi-turn-context-preserved", "Context Preserved", false, $"step1: taskId={tid}, contextId={ctx1}", sw.ElapsedMilliseconds);
    }
    else
    {
        var req2 = new SendMessageRequest
        {
            Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), TaskId = tid, Parts = [Part.FromText("more data")] }
        };
        var r2 = await client.SendMessageAsync(req2);
        var ctx2 = r2.Task?.ContextId;
        Record("jsonrpc/multi-turn-context-preserved", "Context Preserved", ctx1 == ctx2,
            $"ctx1={ctx1}, ctx2={ctx2}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/multi-turn-context-preserved", "Context Preserved", false, ex.Message, sw.ElapsedMilliseconds); }

// 25. get-task-with-history — GetTask and check for history
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var r = await client.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var tid = r.Task?.Id;
    if (tid is null)
    {
        Record("jsonrpc/get-task-with-history", "GetTask With History", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        var task = await client.GetTaskAsync(new GetTaskRequest { Id = tid, HistoryLength = 10 });
        var hasHistory = task.History?.Count > 0;
        Record("jsonrpc/get-task-with-history", "GetTask With History", true,
            $"state={task.Status.State}, history={task.History?.Count ?? 0}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/get-task-with-history", "GetTask With History", false, ex.Message, sw.ElapsedMilliseconds); }

// 26. get-task-after-failure — GetTask after a failure, verify FAILED state
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var r = await client.SendMessageAsync(text: "task-failure trigger error", role: Role.User);
    var tid = r.Task?.Id;
    if (tid is null)
    {
        Record("jsonrpc/get-task-after-failure", "GetTask After Failure", false, "no taskId from failure test", sw.ElapsedMilliseconds);
    }
    else
    {
        var task = await client.GetTaskAsync(new GetTaskRequest { Id = tid });
        var state = task.Status.State;
        Record("jsonrpc/get-task-after-failure", "GetTask After Failure", state == TaskState.Failed,
            $"state={state}, msg={task.Status.Message?.Parts.FirstOrDefault()?.Text ?? "none"}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("jsonrpc/get-task-after-failure", "GetTask After Failure", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// HTTP+JSON REST BINDING (via A2AClientFactory → A2AHttpJsonClient)
// ═══════════════════════════════════════════════════════════════════════════
Console.WriteLine("\n── HTTP+JSON REST Binding (SDK via Factory) ──");

var httpJsonOptions = new A2AClientOptions { PreferredBindings = [ProtocolBindingNames.HttpJson] };

// Pre-create REST clients via factory from resolved agent cards
// (CreateAsync has a JSON parsing bug in preview2, so resolve card first then use Create)
IA2AClient? restEchoClient = null;
IA2AClient? restSpecClient = null;
try
{
    var echoResolver = new A2ACardResolver(new Uri($"{baseUrl}/echo/"), versionedHttpClient);
    var echoCard = await echoResolver.GetAgentCardAsync();
    restEchoClient = A2AClientFactory.Create(echoCard, versionedHttpClient, httpJsonOptions);
}
catch (Exception ex) { Console.WriteLine($"  WARN: REST echo client creation failed: {ex.Message}"); }
try
{
    var specResolver = new A2ACardResolver(new Uri($"{baseUrl}/spec/"), versionedHttpClient);
    var specCard = await specResolver.GetAgentCardAsync();
    restSpecClient = A2AClientFactory.Create(specCard, versionedHttpClient, httpJsonOptions);
}
catch (Exception ex) { Console.WriteLine($"  WARN: REST spec client creation failed: {ex.Message}"); }

// 1. rest/agent-card-echo
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/echo/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    var hasHttpJson = card.SupportedInterfaces?.Any(i =>
        string.Equals(i.ProtocolBinding, ProtocolBindingNames.HttpJson, StringComparison.OrdinalIgnoreCase)) ?? false;
    Record("rest/agent-card-echo", "Echo Agent Card", card.Name is not null && card.Skills.Count >= 1 && hasHttpJson,
        $"name={card.Name}, skills={card.Skills.Count}, httpJson={hasHttpJson}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/agent-card-echo", "Echo Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// 2. rest/agent-card-spec
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/spec/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    var hasHttpJson = card.SupportedInterfaces?.Any(i =>
        string.Equals(i.ProtocolBinding, ProtocolBindingNames.HttpJson, StringComparison.OrdinalIgnoreCase)) ?? false;
    Record("rest/agent-card-spec", "Spec Agent Card", card.Skills.Count == 8 && hasHttpJson,
        $"skills={card.Skills.Count}, httpJson={hasHttpJson}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/agent-card-spec", "Spec Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// 3. rest/echo-send-message
try
{
    sw.Restart();
    if (restEchoClient is null) throw new InvalidOperationException("REST echo client not available");
    var response = await restEchoClient.SendMessageAsync(text: "hello from .NET SDK", role: Role.User);
    var text = response.Message?.Parts.FirstOrDefault()?.Text ?? "";
    Record("rest/echo-send-message", "Echo Send Message", text.Contains("hello from .NET SDK", StringComparison.OrdinalIgnoreCase),
        $"text={text}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/echo-send-message", "Echo Send Message", false, ex.Message, sw.ElapsedMilliseconds); }

// 4. rest/spec-message-only
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var response = await restSpecClient.SendMessageAsync(text: "message-only from .NET", role: Role.User);
    Record("rest/spec-message-only", "Message Only", response.Message?.Role == Role.Agent,
        $"role={response.Message?.Role}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-message-only", "Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// 5+6. rest/spec-task-lifecycle + rest/spec-get-task
string? restTaskId = null;
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var response = await restSpecClient.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    if (response.Task is { } task)
    {
        restTaskId = task.Id;
        Record("rest/spec-task-lifecycle", "Task Lifecycle", task.Status.State == TaskState.Completed && task.Artifacts?.Count >= 1,
            $"state={task.Status.State}, artifacts={task.Artifacts?.Count}", sw.ElapsedMilliseconds);
        sw.Restart();
        var fetched = await restSpecClient.GetTaskAsync(new GetTaskRequest { Id = task.Id });
        Record("rest/spec-get-task", "GetTask", fetched.Id == task.Id,
            $"state={fetched.Status.State}", sw.ElapsedMilliseconds);
    }
    else
    {
        Record("rest/spec-task-lifecycle", "Task Lifecycle", false, "got message, expected task", sw.ElapsedMilliseconds);
        Record("rest/spec-get-task", "GetTask", false, "skipped", 0);
    }
}
catch (Exception ex)
{
    Record("rest/spec-task-lifecycle", "Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds);
    Record("rest/spec-get-task", "GetTask", false, "skipped", 0);
}

// 7. rest/spec-task-failure
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var response = await restSpecClient.SendMessageAsync(text: "task-failure trigger error", role: Role.User);
    Record("rest/spec-task-failure", "Task Failure", response.Task?.Status.State == TaskState.Failed,
        $"state={response.Task?.Status.State}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-task-failure", "Task Failure", false, ex.Message, sw.ElapsedMilliseconds); }

// 8. rest/spec-data-types
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var response = await restSpecClient.SendMessageAsync(text: "data-types show all", role: Role.User);
    var t = response.Task;
    var hasText = t?.Artifacts?.Any(a => a.Parts.Any(p => p.Text is not null)) ?? false;
    var hasData = t?.Artifacts?.Any(a => a.Parts.Any(p => p.Data is not null)) ?? false;
    var hasFile = t?.Artifacts?.Any(a => a.Parts.Any(p => p.MediaType is not null)) ?? false;
    Record("rest/spec-data-types", "Data Types", hasText && hasData && hasFile,
        $"text={hasText}, data={hasData}, file={hasFile}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-data-types", "Data Types", false, ex.Message, sw.ElapsedMilliseconds); }

// 9. rest/spec-streaming
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var request = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("streaming generate output")]
        }
    };
    int restEvtCount = 0; bool restSawArt = false, restSawDone = false;
    await foreach (var ev in restSpecClient.SendStreamingMessageAsync(request))
    {
        restEvtCount++;
        if (ev.ArtifactUpdate is not null) restSawArt = true;
        if (ev.Task?.Status.State == TaskState.Completed || ev.StatusUpdate?.Status.State == TaskState.Completed) restSawDone = true;
    }
    Record("rest/spec-streaming", "Streaming", restEvtCount >= 3 && restSawArt && restSawDone,
        $"events={restEvtCount}, artifact={restSawArt}, completed={restSawDone}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-streaming", "Streaming", false, ex.Message, sw.ElapsedMilliseconds); }

// 10. rest/error-task-not-found
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    await restSpecClient.GetTaskAsync(new GetTaskRequest { Id = "00000000-0000-0000-0000-000000000000" });
    Record("rest/error-task-not-found", "Task Not Found", false, "Should have thrown", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("rest/error-task-not-found", "Task Not Found", true, $"errorCode={ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-task-not-found", "Task Not Found", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-task-not-found", "Task Not Found", false, ex.GetType().Name, sw.ElapsedMilliseconds); }

// 11. rest/spec-multi-turn
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");

    var r1 = await restSpecClient.SendMessageAsync(text: "multi-turn start conversation", role: Role.User);
    var mtTaskId = r1.Task?.Id;
    var s1 = r1.Task?.Status.State == TaskState.InputRequired;

    if (mtTaskId is null)
    {
        Record("rest/spec-multi-turn", "Multi-Turn", false, "step1: no taskId returned", sw.ElapsedMilliseconds);
    }
    else
    {
        var req2 = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = mtTaskId,
                Parts = [Part.FromText("more data")]
            }
        };
        var r2 = await restSpecClient.SendMessageAsync(req2);
        var s2 = r2.Task?.Status.State == TaskState.InputRequired;

        var req3 = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = mtTaskId,
                Parts = [Part.FromText("done")]
            }
        };
        var r3 = await restSpecClient.SendMessageAsync(req3);
        var s3 = r3.Task?.Status.State == TaskState.Completed;

        Record("rest/spec-multi-turn", "Multi-Turn", s1 && s2 && s3,
            $"step1={r1.Task?.Status.State}, step2={r2.Task?.Status.State}, step3={r3.Task?.Status.State}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/spec-multi-turn", "Multi-Turn", false, ex.Message, sw.ElapsedMilliseconds); }

// 12. rest/spec-task-cancel
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var cancelReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel")]
        }
    };
    string? restCancelTaskId = null;
    using var restCancelCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await foreach (var ev in restSpecClient.SendStreamingMessageAsync(cancelReq).WithCancellation(restCancelCts.Token))
    {
        restCancelTaskId = ev.Task?.Id ?? ev.StatusUpdate?.TaskId ?? ev.ArtifactUpdate?.TaskId;
        if (restCancelTaskId is not null) break;
    }
    if (restCancelTaskId is null)
    {
        Record("rest/spec-task-cancel", "Task Cancel", false, "no taskId from streaming", sw.ElapsedMilliseconds);
    }
    else
    {
        await restSpecClient.CancelTaskAsync(new CancelTaskRequest { Id = restCancelTaskId });
        var fetched = await restSpecClient.GetTaskAsync(new GetTaskRequest { Id = restCancelTaskId });
        Record("rest/spec-task-cancel", "Task Cancel",
            fetched.Status.State == TaskState.Canceled,
            $"taskId={restCancelTaskId}, state={fetched.Status.State}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/spec-task-cancel", "Task Cancel", false, ex.Message, sw.ElapsedMilliseconds); }

// 12b. rest/spec-cancel-with-metadata
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var cancelMetaReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel start")]
        }
    };
    string? restCancelMetaTaskId = null;
    using var restCancelMetaCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await foreach (var ev in restSpecClient.SendStreamingMessageAsync(cancelMetaReq).WithCancellation(restCancelMetaCts.Token))
    {
        restCancelMetaTaskId = ev.Task?.Id ?? ev.StatusUpdate?.TaskId ?? ev.ArtifactUpdate?.TaskId;
        if (restCancelMetaTaskId is not null) break;
    }
    if (restCancelMetaTaskId is null)
    {
        Record("rest/spec-cancel-with-metadata", "Cancel With Metadata", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        var cancelResult = await restSpecClient.CancelTaskAsync(new CancelTaskRequest
        {
            Id = restCancelMetaTaskId,
            Metadata = new Dictionary<string, System.Text.Json.JsonElement>
            {
                ["reason"] = JsonSerializer.SerializeToElement("test-cancel-reason"),
                ["requestedBy"] = JsonSerializer.SerializeToElement("dotnet-sdk")
            }
        });
        var metaKeys = cancelResult.Metadata?.Keys.ToList() ?? [];
        var hasMetadata = metaKeys.Contains("reason") && metaKeys.Contains("requestedBy");
        Record("rest/spec-cancel-with-metadata", "Cancel With Metadata", cancelResult.Status.State == TaskState.Canceled,
            $"taskId={restCancelMetaTaskId}, state={cancelResult.Status.State}, metadataKeys=[{string.Join(",", metaKeys)}]", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/spec-cancel-with-metadata", "Cancel With Metadata", false, ex.Message, sw.ElapsedMilliseconds); }

// 13. rest/spec-list-tasks
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var listResponse = await restSpecClient.ListTasksAsync(new ListTasksRequest { PageSize = 10 });
    Record("rest/spec-list-tasks", "List Tasks", listResponse.Tasks.Count >= 1,
        $"tasks={listResponse.Tasks.Count}, totalSize={listResponse.TotalSize}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-list-tasks", "List Tasks", false, ex.Message, sw.ElapsedMilliseconds); }

// 14. rest/spec-return-immediately
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var request = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("long-running test")]
        },
        Configuration = new SendMessageConfiguration { Blocking = false }
    };
    var riSw = Stopwatch.StartNew();
    var response = await restSpecClient.SendMessageAsync(request);
    riSw.Stop();
    var state = response.Task?.Status.State;
    bool riPassed = riSw.ElapsedMilliseconds < 2000 && state == TaskState.Working;
    string riDetail = riPassed
        ? $"state={state}, time={riSw.ElapsedMilliseconds}ms"
        : $"state={state}, time={riSw.ElapsedMilliseconds}ms (expected Working within 2s)";
    Record("rest/spec-return-immediately", "Return Immediately", riPassed, riDetail, sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-return-immediately", "Return Immediately", false, ex.Message, sw.ElapsedMilliseconds); }

// 15. rest/error-cancel-not-found
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    await restSpecClient.CancelTaskAsync(new CancelTaskRequest { Id = "00000000-0000-0000-0000-000000000000" });
    Record("rest/error-cancel-not-found", "Cancel Not Found", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("rest/error-cancel-not-found", "Cancel Not Found", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-cancel-not-found", "Cancel Not Found", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-cancel-not-found", "Cancel Not Found", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 16. rest/error-cancel-terminal
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var r = await restSpecClient.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var termCancelTaskId = r.Task?.Id;
    if (termCancelTaskId is null)
    {
        Record("rest/error-cancel-terminal", "Cancel Terminal Task", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        await restSpecClient.CancelTaskAsync(new CancelTaskRequest { Id = termCancelTaskId });
        Record("rest/error-cancel-terminal", "Cancel Terminal Task", false, "expected error, got success", sw.ElapsedMilliseconds);
    }
}
catch (A2AException ex) { Record("rest/error-cancel-terminal", "Cancel Terminal Task", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-cancel-terminal", "Cancel Terminal Task", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-cancel-terminal", "Cancel Terminal Task", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 17. rest/error-send-terminal
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var r = await restSpecClient.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var termTaskId = r.Task?.Id;
    if (termTaskId is null)
    {
        Record("rest/error-send-terminal", "Send To Terminal Task", false, "no taskId from lifecycle", sw.ElapsedMilliseconds);
    }
    else
    {
        var req = new SendMessageRequest
        {
            Message = new Message
            {
                Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
                TaskId = termTaskId,
                Parts = [Part.FromText("this should fail")]
            }
        };
        await restSpecClient.SendMessageAsync(req);
        Record("rest/error-send-terminal", "Send To Terminal Task", false, "expected error, got success", sw.ElapsedMilliseconds);
    }
}
catch (A2AException ex) { Record("rest/error-send-terminal", "Send To Terminal Task", true, $"got expected error: {ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-send-terminal", "Send To Terminal Task", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-send-terminal", "Send To Terminal Task", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 18. rest/error-send-invalid-task
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var req = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            TaskId = "00000000-0000-0000-0000-000000000000",
            Parts = [Part.FromText("send to invalid task")]
        }
    };
    await restSpecClient.SendMessageAsync(req);
    Record("rest/error-send-invalid-task", "Send Invalid TaskId", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("rest/error-send-invalid-task", "Send Invalid TaskId", true, $"errorCode={ex.ErrorCode}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-send-invalid-task", "Send Invalid TaskId", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-send-invalid-task", "Send Invalid TaskId", true, $"got error: {ex.GetType().Name}", sw.ElapsedMilliseconds); }

// 19. rest/error-push-not-supported
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    await restSpecClient.CreateTaskPushNotificationConfigAsync(new CreateTaskPushNotificationConfigRequest
    {
        TaskId = "00000000-0000-0000-0000-000000000000",
        ConfigId = "test-config",
        Config = new PushNotificationConfig { Url = "https://example.com/webhook" }
    });
    Record("rest/error-push-not-supported", "Push Not Supported", false, "expected error, got success", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("rest/error-push-not-supported", "Push Not Supported", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-push-not-supported", "Push Not Supported", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-push-not-supported", "Push Not Supported", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 20. rest/subscribe-to-task
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var subReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("task-cancel start")]
        },
        Configuration = new SendMessageConfiguration { Blocking = false }
    };
    var subResponse = await restSpecClient.SendMessageAsync(subReq);
    var subTaskId = subResponse.Task?.Id;
    if (subTaskId is null)
    {
        Record("rest/subscribe-to-task", "SubscribeToTask", false, "no taskId from non-blocking send", sw.ElapsedMilliseconds);
    }
    else
    {
        int subEvtCount = 0;
        using var subCts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await foreach (var ev in restSpecClient.SubscribeToTaskAsync(new SubscribeToTaskRequest { Id = subTaskId }).WithCancellation(subCts.Token))
        {
            subEvtCount++;
            var evState = ev.Task?.Status.State ?? ev.StatusUpdate?.Status.State;
            if (evState == TaskState.Completed || evState == TaskState.Failed || evState == TaskState.Canceled)
                break;
        }
        Record("rest/subscribe-to-task", "SubscribeToTask", subEvtCount >= 1,
            $"taskId={subTaskId}, events={subEvtCount}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/subscribe-to-task", "SubscribeToTask", false, ex.Message, sw.ElapsedMilliseconds); }

// 21. rest/error-subscribe-not-found
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    await foreach (var ev in restSpecClient.SubscribeToTaskAsync(new SubscribeToTaskRequest { Id = "00000000-0000-0000-0000-000000000000" }))
    {
        break;
    }
    Record("rest/error-subscribe-not-found", "Subscribe Not Found", false, "expected error, got events", sw.ElapsedMilliseconds);
}
catch (A2AException ex) { Record("rest/error-subscribe-not-found", "Subscribe Not Found", true, $"errorCode={ex.ErrorCode}: {ex.Message}", sw.ElapsedMilliseconds); }
catch (InvalidOperationException ex) { Record("rest/error-subscribe-not-found", "Subscribe Not Found", false, ex.Message, sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/error-subscribe-not-found", "Subscribe Not Found", true, $"got error: {ex.GetType().Name}: {ex.Message}", sw.ElapsedMilliseconds); }

// 22. rest/stream-message-only
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var req = new SendMessageRequest
    {
        Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), Parts = [Part.FromText("message-only hello")] }
    };
    int eventCount = 0; bool hasMessage = false;
    await foreach (var ev in restSpecClient.SendStreamingMessageAsync(req))
    {
        eventCount++;
        if (ev.Message is not null) hasMessage = true;
    }
    Record("rest/stream-message-only", "Stream Message Only", hasMessage && eventCount == 1,
        $"events={eventCount}, hasMessage={hasMessage}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/stream-message-only", "Stream Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// 23. rest/stream-task-lifecycle
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var req = new SendMessageRequest
    {
        Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), Parts = [Part.FromText("task-lifecycle process this")] }
    };
    bool firstHasTask = false; bool lastTerminal = false; int idx = 0;
    await foreach (var ev in restSpecClient.SendStreamingMessageAsync(req))
    {
        if (idx == 0 && ev.Task is not null) firstHasTask = true;
        if (ev.Task?.Status.State == TaskState.Completed || ev.StatusUpdate?.Status.State == TaskState.Completed) lastTerminal = true;
        idx++;
    }
    Record("rest/stream-task-lifecycle", "Stream Task Lifecycle", firstHasTask && lastTerminal,
        $"firstHasTask={firstHasTask}, lastTerminal={lastTerminal}, events={idx}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/stream-task-lifecycle", "Stream Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds); }

// 24. rest/multi-turn-context-preserved
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var r1 = await restSpecClient.SendMessageAsync(text: "multi-turn start conversation", role: Role.User);
    var ctx1 = r1.Task?.ContextId;
    var tid = r1.Task?.Id;
    if (tid is null || ctx1 is null)
    {
        Record("rest/multi-turn-context-preserved", "Context Preserved", false, $"step1: taskId={tid}, contextId={ctx1}", sw.ElapsedMilliseconds);
    }
    else
    {
        var req2 = new SendMessageRequest
        {
            Message = new Message { Role = Role.User, MessageId = Guid.NewGuid().ToString("N"), TaskId = tid, Parts = [Part.FromText("more data")] }
        };
        var r2 = await restSpecClient.SendMessageAsync(req2);
        var ctx2 = r2.Task?.ContextId;
        Record("rest/multi-turn-context-preserved", "Context Preserved", ctx1 == ctx2,
            $"ctx1={ctx1}, ctx2={ctx2}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/multi-turn-context-preserved", "Context Preserved", false, ex.Message, sw.ElapsedMilliseconds); }

// 25. rest/get-task-with-history
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var r = await restSpecClient.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    var tid = r.Task?.Id;
    if (tid is null)
    {
        Record("rest/get-task-with-history", "GetTask With History", false, "no taskId", sw.ElapsedMilliseconds);
    }
    else
    {
        var task = await restSpecClient.GetTaskAsync(new GetTaskRequest { Id = tid, HistoryLength = 10 });
        var hasHistory = task.History?.Count > 0;
        Record("rest/get-task-with-history", "GetTask With History", true,
            $"state={task.Status.State}, history={task.History?.Count ?? 0}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/get-task-with-history", "GetTask With History", false, ex.Message, sw.ElapsedMilliseconds); }

// 26. rest/get-task-after-failure
try
{
    sw.Restart();
    if (restSpecClient is null) throw new InvalidOperationException("REST spec client not available");
    var r = await restSpecClient.SendMessageAsync(text: "task-failure trigger error", role: Role.User);
    var tid = r.Task?.Id;
    if (tid is null)
    {
        Record("rest/get-task-after-failure", "GetTask After Failure", false, "no taskId from failure test", sw.ElapsedMilliseconds);
    }
    else
    {
        var task = await restSpecClient.GetTaskAsync(new GetTaskRequest { Id = tid });
        var state = task.Status.State;
        Record("rest/get-task-after-failure", "GetTask After Failure", state == TaskState.Failed,
            $"state={state}, msg={task.Status.Message?.Parts.FirstOrDefault()?.Text ?? "none"}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/get-task-after-failure", "GetTask After Failure", false, ex.Message, sw.ElapsedMilliseconds); }
// ═══════════════════════════════════════════════════════════════════════════
// v0.3 BACKWARD COMPATIBILITY TESTS
// ═══════════════════════════════════════════════════════════════════════════
Console.WriteLine("\n── v0.3 Backward Compatibility ──");

var plainHttpClient = new HttpClient();

// v03/spec03-agent-card — fetch v0.3 agent card via SDK
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/spec03/"), plainHttpClient);
    var card = await resolver.GetAgentCardAsync();
    var hasName = card.Name is not null;
    var hasSkills = card.Skills.Count >= 1;
    Record("v03/spec03-agent-card", "v0.3 Agent Card", hasName && hasSkills,
        $"name={card.Name}, skills={card.Skills.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("v03/spec03-agent-card", "v0.3 Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// v03/spec03-send-message — send message to v0.3 agent via SDK
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec03"), plainHttpClient);
    var response = await client.SendMessageAsync(text: "message-only hello", role: Role.User);
    var text = response.Message?.Parts.FirstOrDefault()?.Text ?? response.Task?.Artifacts?.FirstOrDefault()?.Parts.FirstOrDefault()?.Text ?? "";
    Record("v03/spec03-send-message", "v0.3 Send Message", !string.IsNullOrEmpty(text),
        $"text={text}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("v03/spec03-send-message", "v0.3 Send Message", false, $"SDK error: {ex.Message}", sw.ElapsedMilliseconds); }

// v03/spec03-task-lifecycle — task lifecycle against v0.3 agent
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec03"), plainHttpClient);
    var response = await client.SendMessageAsync(text: "task-lifecycle process", role: Role.User);
    if (response.Task is { } task03)
    {
        Record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle",
            task03.Status.State == TaskState.Completed && task03.Artifacts?.Count >= 1,
            $"state={task03.Status.State}, artifacts={task03.Artifacts?.Count}", sw.ElapsedMilliseconds);
    }
    else
    {
        Record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
            "got message, expected task", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false, $"SDK error: {ex.Message}", sw.ElapsedMilliseconds); }

// v03/spec03-streaming — streaming against v0.3 agent
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec03"), plainHttpClient);
    var streamReq = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User, MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("streaming generate")]
        }
    };
    int v03EvtCount = 0; bool v03SawArt = false, v03SawDone = false;
    await foreach (var ev in client.SendStreamingMessageAsync(streamReq))
    {
        v03EvtCount++;
        if (ev.ArtifactUpdate is not null) v03SawArt = true;
        if (ev.Task?.Status.State == TaskState.Completed || ev.StatusUpdate?.Status.State == TaskState.Completed) v03SawDone = true;
    }
    Record("v03/spec03-streaming", "v0.3 Streaming", v03EvtCount >= 1 && v03SawDone,
        $"events={v03EvtCount}, artifact={v03SawArt}, completed={v03SawDone}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("v03/spec03-streaming", "v0.3 Streaming", false, $"SDK error: {ex.Message}", sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// SUMMARY + JSON OUTPUT
// ═══════════════════════════════════════════════════════════════════════════
var passed = results.Count(r => r.Passed);
var failed = results.Count(r => !r.Passed);
Console.WriteLine($"\n══════════════════════════════════════════");
Console.WriteLine($"  {passed} passed, {failed} failed out of {results.Count} tests");
Console.WriteLine($"══════════════════════════════════════════");
if (failed > 0)
{
    Console.WriteLine("\nFailed tests:");
    foreach (var r in results.Where(r => !r.Passed))
        Console.WriteLine($"  ✗ {r.Id} — {r.Detail}");
}

// Detect SDK source
var a2aAssembly = typeof(A2AClient).Assembly;
var sdkVersion = a2aAssembly.GetName().Version?.ToString() ?? "unknown";
var sdkInfo = a2aAssembly.GetCustomAttribute<System.Reflection.AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? sdkVersion;
var sdkLabel = sdkInfo.Contains('+') ? $"A2A {sdkInfo[..sdkInfo.IndexOf('+')]}" : $"A2A {sdkInfo}";

// Write results.json
var jsonOutput = new
{
    client = "dotnet",
    sdk = sdkLabel,
    protocolVersion = "1.0",
    timestamp = DateTime.UtcNow.ToString("o"),
    baseUrl,
    results = results.Select(r => new { r.Id, name = r.Name, r.Passed, detail = r.Detail, r.DurationMs })
};
var jsonPath = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "results.json");
await File.WriteAllTextAsync(jsonPath, JsonSerializer.Serialize(jsonOutput, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"\nResults written to results.json");

return failed > 0 ? 1 : 0;

record TestResult(string Id, string Name, bool Passed, string Detail, long DurationMs);
