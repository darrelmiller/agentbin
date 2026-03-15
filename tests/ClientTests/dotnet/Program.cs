/// A2A .NET SDK acceptance tests against the AgentBin service.
/// Standardized test IDs for cross-language compatibility dashboard.
/// Usage: dotnet run [baseUrl]

using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using A2A;

var baseUrl = args.Length > 0
    ? args[0].TrimEnd('/')
    : "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";

Console.WriteLine($"AgentBin .NET Client Tests — {baseUrl}\n");

var results = new List<TestResult>();
var http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
http.DefaultRequestHeaders.Add("A2A-Version", "1.0");
var versionedHttpClient = new HttpClient();
versionedHttpClient.DefaultRequestHeaders.Add("A2A-Version", "1.0");

void Record(string id, string name, bool passed, string detail, long durationMs)
{
    results.Add(new TestResult(id, name, passed, detail, durationMs));
    var tag = passed ? "PASS" : "FAIL";
    Console.WriteLine($"  [{tag}] {id} — {detail}");
}


// ═══════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════
// 1. agent-card-echo
// ═══════════════════════════════════════════════════════════════════════════
var sw = Stopwatch.StartNew();
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/echo/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    Record("agent-card-echo", "Echo Agent Card", card.Name is not null && card.Skills.Count >= 1,
        $"name={card.Name}, skills={card.Skills.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("agent-card-echo", "Echo Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 2. agent-card-spec
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var resolver = new A2ACardResolver(new Uri($"{baseUrl}/spec/"), versionedHttpClient);
    var card = await resolver.GetAgentCardAsync();
    Record("agent-card-spec", "Spec Agent Card", card.Skills.Count == 8 && (card.Capabilities.Streaming ?? false),
        $"skills={card.Skills.Count}, streaming={card.Capabilities.Streaming}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("agent-card-spec", "Spec Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 3. echo-send-message
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/echo"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "hello from .NET SDK", role: Role.User);
    var text = response.Message?.Parts.FirstOrDefault()?.Text ?? "";
    Record("echo-send-message", "Echo Send Message", text.Contains("hello from .NET SDK", StringComparison.OrdinalIgnoreCase),
        $"text={text}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("echo-send-message", "Echo Send Message", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 4. spec-message-only
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "message-only from .NET", role: Role.User);
    var isMessage = response.Message is not null;
    Record("spec-message-only", "Message Only", isMessage && response.Message!.Role == Role.Agent,
        $"isMessage={isMessage}, role={response.Message?.Role}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("spec-message-only", "Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 5. spec-task-lifecycle  +  6. spec-get-task
// ═══════════════════════════════════════════════════════════════════════════
string? lifecycleTaskId = null;
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "task-lifecycle process this", role: Role.User);
    if (response.Task is { } task)
    {
        lifecycleTaskId = task.Id;
        Record("spec-task-lifecycle", "Task Lifecycle", task.Status.State == TaskState.Completed && task.Artifacts?.Count >= 1,
            $"state={task.Status.State}, artifacts={task.Artifacts?.Count}", sw.ElapsedMilliseconds);

        sw.Restart();
        var fetched = await client.GetTaskAsync(new GetTaskRequest { Id = task.Id });
        Record("spec-get-task", "GetTask", fetched.Id == task.Id && fetched.Status.State == TaskState.Completed,
            $"idMatch={fetched.Id == task.Id}, state={fetched.Status.State}", sw.ElapsedMilliseconds);
    }
    else
    {
        Record("spec-task-lifecycle", "Task Lifecycle", false, "Expected task, got message", sw.ElapsedMilliseconds);
        Record("spec-get-task", "GetTask", false, "skipped — no task", 0);
    }
}
catch (Exception ex)
{
    Record("spec-task-lifecycle", "Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds);
    Record("spec-get-task", "GetTask", false, "skipped", 0);
}

// ═══════════════════════════════════════════════════════════════════════════
// 7. spec-task-failure
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "task-failure trigger error", role: Role.User);
    Record("spec-task-failure", "Task Failure", response.Task?.Status.State == TaskState.Failed,
        $"state={response.Task?.Status.State}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("spec-task-failure", "Task Failure", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 8. spec-data-types
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var response = await client.SendMessageAsync(text: "data-types show all", role: Role.User);
    var task = response.Task;
    var hasText = task?.Artifacts?.Any(a => a.Parts.Any(p => p.Text is not null)) ?? false;
    var hasData = task?.Artifacts?.Any(a => a.Parts.Any(p => p.Data is not null)) ?? false;
    var hasFile = task?.Artifacts?.Any(a => a.Parts.Any(p => p.MediaType is not null)) ?? false;
    Record("spec-data-types", "Data Types", hasText && hasData && hasFile,
        $"text={hasText}, data={hasData}, file={hasFile}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("spec-data-types", "Data Types", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 9. spec-streaming
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    var request = new SendMessageRequest
    {
        Message = new Message
        {
            Role = Role.User,
            MessageId = Guid.NewGuid().ToString("N"),
            Parts = [Part.FromText("streaming generate output")]
        }
    };
    int eventCount = 0;
    bool sawArtifact = false, sawCompleted = false;
    await foreach (var ev in client.SendStreamingMessageAsync(request))
    {
        eventCount++;
        if (ev.ArtifactUpdate is not null) sawArtifact = true;
        if (ev.Task?.Status.State == TaskState.Completed) sawCompleted = true;
        if (ev.StatusUpdate?.Status.State == TaskState.Completed) sawCompleted = true;
    }
    Record("spec-streaming", "Streaming", eventCount >= 3 && sawArtifact && sawCompleted,
        $"events={eventCount}, artifact={sawArtifact}, completed={sawCompleted}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("spec-streaming", "Streaming", false, ex.Message, sw.ElapsedMilliseconds); }

// ═══════════════════════════════════════════════════════════════════════════
// 10. error-task-not-found
// ═══════════════════════════════════════════════════════════════════════════
try
{
    sw.Restart();
    var client = new A2AClient(new Uri($"{baseUrl}/spec"), versionedHttpClient);
    await client.GetTaskAsync(new GetTaskRequest { Id = "00000000-0000-0000-0000-000000000000" });
    Record("error-task-not-found", "Task Not Found Error", false, "Should have thrown", sw.ElapsedMilliseconds);
}
catch (A2AException ex)
{
    Record("error-task-not-found", "Task Not Found Error", true,
        $"errorCode={ex.ErrorCode}", sw.ElapsedMilliseconds);
}
catch (Exception ex)
{
    Record("error-task-not-found", "Task Not Found Error", false,
        $"Wrong exception: {ex.GetType().Name}", sw.ElapsedMilliseconds);
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

// Write results.json
var jsonOutput = new
{
    client = "dotnet",
    sdk = "A2A 1.0.0-alpha",
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
