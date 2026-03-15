/// A2A .NET SDK acceptance tests against the AgentBin service.
/// Tests both JSON-RPC (via SDK) and HTTP+JSON REST bindings.
/// Usage: dotnet run [baseUrl]

using System.Diagnostics;
using System.Net;
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

async Task<HttpResponseMessage> RestPost(string url, object body)
{
    var json = JsonSerializer.Serialize(body);
    var req = new HttpRequestMessage(HttpMethod.Post, url)
    {
        Content = new StringContent(json, Encoding.UTF8, "application/json")
    };
    req.Headers.Add("A2A-Version", "1.0");
    return await http.SendAsync(req);
}

async Task<HttpResponseMessage> RestGet(string url)
{
    var req = new HttpRequestMessage(HttpMethod.Get, url);
    req.Headers.Add("A2A-Version", "1.0");
    return await http.SendAsync(req);
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

// ═══════════════════════════════════════════════════════════════════════════
// HTTP+JSON REST BINDING (raw HTTP)
// ═══════════════════════════════════════════════════════════════════════════
Console.WriteLine("\n── HTTP+JSON REST Binding ──");

// 1. agent-card via REST
try
{
    sw.Restart();
    var resp = await RestGet($"{baseUrl}/echo/v1/card");
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var name = json?["name"]?.GetValue<string>();
    Record("rest/agent-card-echo", "Echo Agent Card", resp.IsSuccessStatusCode && name is not null,
        $"name={name}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/agent-card-echo", "Echo Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

try
{
    sw.Restart();
    var resp = await RestGet($"{baseUrl}/spec/v1/card");
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var skills = json?["skills"] as JsonArray;
    Record("rest/agent-card-spec", "Spec Agent Card", resp.IsSuccessStatusCode && (skills?.Count ?? 0) == 8,
        $"skills={skills?.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/agent-card-spec", "Spec Agent Card", false, ex.Message, sw.ElapsedMilliseconds); }

// 3. echo via REST
try
{
    sw.Restart();
    var resp = await RestPost($"{baseUrl}/echo/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "hello REST from .NET" } } }
    });
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var text = json?["message"]?["parts"]?[0]?["text"]?.GetValue<string>() ?? "";
    Record("rest/echo-send-message", "Echo Send Message", text.Contains("hello REST"),
        $"text={text}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/echo-send-message", "Echo Send Message", false, ex.Message, sw.ElapsedMilliseconds); }

// 4. message-only via REST
try
{
    sw.Restart();
    var resp = await RestPost($"{baseUrl}/spec/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "message-only REST" } } }
    });
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var hasMsg = json?["message"] is not null;
    var hasTask = json?["task"] is not null;
    Record("rest/spec-message-only", "Message Only", hasMsg && !hasTask,
        $"message={hasMsg}, task={hasTask}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-message-only", "Message Only", false, ex.Message, sw.ElapsedMilliseconds); }

// 5+6. task-lifecycle + get-task via REST
string? restTaskId = null;
try
{
    sw.Restart();
    var resp = await RestPost($"{baseUrl}/spec/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "task-lifecycle REST" } } }
    });
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var state = json?["task"]?["status"]?["state"]?.GetValue<string>();
    restTaskId = json?["task"]?["id"]?.GetValue<string>();
    var artCount = (json?["task"]?["artifacts"] as JsonArray)?.Count ?? 0;
    Record("rest/spec-task-lifecycle", "Task Lifecycle", state == "TASK_STATE_COMPLETED" && artCount >= 1,
        $"state={state}, artifacts={artCount}", sw.ElapsedMilliseconds);

    if (restTaskId is not null)
    {
        sw.Restart();
        var getResp = await RestGet($"{baseUrl}/spec/v1/tasks/{restTaskId}");
        var getJson = JsonNode.Parse(await getResp.Content.ReadAsStringAsync());
        var getId = getJson?["id"]?.GetValue<string>();
        Record("rest/spec-get-task", "GetTask", getId == restTaskId,
            $"id={getId}, status={getResp.StatusCode}", sw.ElapsedMilliseconds);
    }
    else
    {
        Record("rest/spec-get-task", "GetTask", false, "no taskId", 0);
    }
}
catch (Exception ex)
{
    Record("rest/spec-task-lifecycle", "Task Lifecycle", false, ex.Message, sw.ElapsedMilliseconds);
    Record("rest/spec-get-task", "GetTask", false, "skipped", 0);
}

// 7. task-failure via REST
try
{
    sw.Restart();
    var resp = await RestPost($"{baseUrl}/spec/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "task-failure trigger" } } }
    });
    var json = JsonNode.Parse(await resp.Content.ReadAsStringAsync());
    var state = json?["task"]?["status"]?["state"]?.GetValue<string>();
    Record("rest/spec-task-failure", "Task Failure", state == "TASK_STATE_FAILED",
        $"state={state}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-task-failure", "Task Failure", false, ex.Message, sw.ElapsedMilliseconds); }

// 8. data-types via REST
try
{
    sw.Restart();
    var resp = await RestPost($"{baseUrl}/spec/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "data-types show all" } } }
    });
    var raw = await resp.Content.ReadAsStringAsync();
    var hasText = raw.Contains("\"text\"");
    var hasData = raw.Contains("\"data\"");
    var hasFile = raw.Contains("\"mediaType\"");
    Record("rest/spec-data-types", "Data Types", hasText && hasData && hasFile,
        $"text={hasText}, data={hasData}, file={hasFile}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-data-types", "Data Types", false, ex.Message, sw.ElapsedMilliseconds); }

// 9. streaming via REST (POST /v1/message:stream)
try
{
    sw.Restart();
    var body = JsonSerializer.Serialize(new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "streaming generate output" } } }
    });
    var req = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec/v1/message:stream")
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json")
    };
    req.Headers.Add("A2A-Version", "1.0");
    req.Headers.Add("Accept", "text/event-stream");
    var resp = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead);
    using var stream = await resp.Content.ReadAsStreamAsync();
    using var reader = new StreamReader(stream);
    int sseCount = 0;
    while (await reader.ReadLineAsync() is { } line)
    {
        if (line.StartsWith("data:")) sseCount++;
    }
    Record("rest/spec-streaming", "Streaming", sseCount >= 3,
        $"sseEvents={sseCount}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-streaming", "Streaming", false, ex.Message, sw.ElapsedMilliseconds); }

// 10. error-task-not-found via REST (GET /v1/tasks/{id} → 404)
try
{
    sw.Restart();
    var resp = await RestGet($"{baseUrl}/spec/v1/tasks/00000000-0000-0000-0000-000000000000");
    Record("rest/error-task-not-found", "Task Not Found", resp.StatusCode == HttpStatusCode.NotFound,
        $"status={resp.StatusCode}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/error-task-not-found", "Task Not Found", false, ex.Message, sw.ElapsedMilliseconds); }

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
