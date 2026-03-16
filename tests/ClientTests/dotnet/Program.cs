/// A2A .NET SDK acceptance tests against the AgentBin service.
/// Tests JSON-RPC binding via SDK; REST tests record honest failure (SDK has no REST transport).
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

// 12. spec-task-cancel — cancel a running task via streaming
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
    using var streamCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await foreach (var ev in client.SendStreamingMessageAsync(cancelReq).WithCancellation(streamCts.Token))
    {
        cancelTaskId = ev.Task?.Id ?? ev.StatusUpdate?.TaskId ?? ev.ArtifactUpdate?.TaskId;
        if (cancelTaskId is not null) break;
    }
    Record("jsonrpc/spec-task-cancel", "Task Cancel", false,
        "SDK does not support CancelTask — method not available in A2A .NET SDK", sw.ElapsedMilliseconds);
}
catch (OperationCanceledException) { Record("jsonrpc/spec-task-cancel", "Task Cancel", false, "SDK does not support CancelTask — method not available in A2A .NET SDK", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/spec-task-cancel", "Task Cancel", false, ex.Message, sw.ElapsedMilliseconds); }

// 13. spec-list-tasks — SDK does not support ListTasks
sw.Restart();
Record("jsonrpc/spec-list-tasks", "List Tasks", false,
    "SDK does not support ListTasks — method not available in A2A .NET SDK", sw.ElapsedMilliseconds);

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

// ═══════════════════════════════════════════════════════════════════════════
// HTTP+JSON REST BINDING — SDK does not support REST transport
// ═══════════════════════════════════════════════════════════════════════════
Console.WriteLine("\n── HTTP+JSON REST Binding ──");

var restTests = new (string Id, string Name)[]
{
    ("rest/agent-card-echo", "Echo Agent Card"),
    ("rest/agent-card-spec", "Spec Agent Card"),
    ("rest/echo-send-message", "Echo Send Message"),
    ("rest/spec-message-only", "Message Only"),
    ("rest/spec-task-lifecycle", "Task Lifecycle"),
    ("rest/spec-get-task", "GetTask"),
    ("rest/spec-task-failure", "Task Failure"),
    ("rest/spec-data-types", "Data Types"),
    ("rest/spec-streaming", "Streaming"),
    ("rest/error-task-not-found", "Task Not Found"),
    ("rest/spec-multi-turn", "Multi-Turn"),
    ("rest/spec-task-cancel", "Task Cancel"),
    ("rest/spec-list-tasks", "List Tasks"),
    ("rest/spec-return-immediately", "Return Immediately"),
};

foreach (var (id, name) in restTests)
{
    Record(id, name, false, "SDK does not support REST (HTTP+JSON) transport", 0);
}

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
var sdkLabel = sdkInfo.Contains("-") || sdkInfo.Contains("+") 
    ? $"a2a-dotnet (local build, {sdkInfo})" 
    : $"A2A {sdkInfo}";

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
