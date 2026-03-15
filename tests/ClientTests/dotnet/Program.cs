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

    if (cancelTaskId is null)
    {
        Record("jsonrpc/spec-task-cancel", "Task Cancel", false, "no taskId from stream", sw.ElapsedMilliseconds);
    }
    else
    {
        // Send CancelTask via raw JSON-RPC HTTP
        var cancelBody = JsonSerializer.Serialize(new { jsonrpc = "2.0", id = 99, method = "CancelTask", @params = new { id = cancelTaskId } });
        var cancelHttpReq = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec")
        {
            Content = new StringContent(cancelBody, Encoding.UTF8, "application/json")
        };
        cancelHttpReq.Headers.Add("A2A-Version", "1.0");
        var cancelResp = await http.SendAsync(cancelHttpReq);
        var cancelJson = JsonNode.Parse(await cancelResp.Content.ReadAsStringAsync());
        var cancelState = cancelJson?["result"]?["status"]?["state"]?.GetValue<string>();
        Record("jsonrpc/spec-task-cancel", "Task Cancel", cancelState == "TASK_STATE_CANCELED",
            $"state={cancelState}", sw.ElapsedMilliseconds);
    }
}
catch (OperationCanceledException) { Record("jsonrpc/spec-task-cancel", "Task Cancel", false, "streaming timed out before taskId", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("jsonrpc/spec-task-cancel", "Task Cancel", false, ex.Message, sw.ElapsedMilliseconds); }

// 13. spec-list-tasks — list tasks (expects at least 1 from earlier tests)
try
{
    sw.Restart();
    var listBody = JsonSerializer.Serialize(new { jsonrpc = "2.0", id = 100, method = "ListTasks", @params = new { } });
    var listReq = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec")
    {
        Content = new StringContent(listBody, Encoding.UTF8, "application/json")
    };
    listReq.Headers.Add("A2A-Version", "1.0");
    var listResp = await http.SendAsync(listReq);
    var listJson = JsonNode.Parse(await listResp.Content.ReadAsStringAsync());
    var tasks = listJson?["result"]?["tasks"] as JsonArray;
    Record("jsonrpc/spec-list-tasks", "List Tasks", (tasks?.Count ?? 0) >= 1,
        $"count={tasks?.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("jsonrpc/spec-list-tasks", "List Tasks", false, ex.Message, sw.ElapsedMilliseconds); }

// 14. spec-return-immediately — test returnImmediately flag (expected to fail)
try
{
    sw.Restart();
    var riClient = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
    var riBody = JsonSerializer.Serialize(new
    {
        jsonrpc = "2.0", id = 101, method = "SendMessage",
        @params = new
        {
            message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER", parts = new[] { new { text = "long-running test" } } },
            configuration = new { returnImmediately = true }
        }
    });
    var riReq = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec")
    {
        Content = new StringContent(riBody, Encoding.UTF8, "application/json")
    };
    riReq.Headers.Add("A2A-Version", "1.0");
    var riSw = Stopwatch.StartNew();
    var riResp = await riClient.SendAsync(riReq);
    riSw.Stop();
    var riJson = JsonNode.Parse(await riResp.Content.ReadAsStringAsync());
    var riState = riJson?["result"]?["task"]?["status"]?["state"]?.GetValue<string>()
              ?? riJson?["result"]?["status"]?["state"]?.GetValue<string>();
    bool riPassed = riSw.ElapsedMilliseconds < 2000 && riState == "TASK_STATE_WORKING";
    string riDetail = riPassed
        ? $"state={riState}, time={riSw.ElapsedMilliseconds}ms"
        : $"returnImmediately ignored by SDK — state={riState}, time={riSw.ElapsedMilliseconds}ms";
    Record("jsonrpc/spec-return-immediately", "Return Immediately", riPassed, riDetail, sw.ElapsedMilliseconds);
    riClient.Dispose();
}
catch (Exception ex) { Record("jsonrpc/spec-return-immediately", "Return Immediately", false, ex.Message, sw.ElapsedMilliseconds); }

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

// 11. spec-multi-turn via REST — 3-step multi-turn conversation
try
{
    sw.Restart();
    // Step 1: start conversation
    var mt1 = await RestPost($"{baseUrl}/spec/v1/message:send", new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "multi-turn start conversation" } } }
    });
    var mt1Json = JsonNode.Parse(await mt1.Content.ReadAsStringAsync());
    var mtRestTaskId = mt1Json?["task"]?["id"]?.GetValue<string>();
    var mt1State = mt1Json?["task"]?["status"]?["state"]?.GetValue<string>();

    if (mtRestTaskId is null)
    {
        Record("rest/spec-multi-turn", "Multi-Turn", false, "step1: no taskId returned", sw.ElapsedMilliseconds);
    }
    else
    {
        // Step 2: follow-up with taskId
        var mt2 = await RestPost($"{baseUrl}/spec/v1/message:send", new
        {
            message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
                taskId = mtRestTaskId,
                parts = new[] { new { text = "more data" } } }
        });
        var mt2Json = JsonNode.Parse(await mt2.Content.ReadAsStringAsync());
        var mt2State = mt2Json?["task"]?["status"]?["state"]?.GetValue<string>();

        // Step 3: finish
        var mt3 = await RestPost($"{baseUrl}/spec/v1/message:send", new
        {
            message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
                taskId = mtRestTaskId,
                parts = new[] { new { text = "done" } } }
        });
        var mt3Json = JsonNode.Parse(await mt3.Content.ReadAsStringAsync());
        var mt3State = mt3Json?["task"]?["status"]?["state"]?.GetValue<string>();

        bool mtPassed = mt1State == "TASK_STATE_INPUT_REQUIRED" && mt2State == "TASK_STATE_INPUT_REQUIRED" && mt3State == "TASK_STATE_COMPLETED";
        Record("rest/spec-multi-turn", "Multi-Turn", mtPassed,
            $"step1={mt1State}, step2={mt2State}, step3={mt3State}", sw.ElapsedMilliseconds);
    }
}
catch (Exception ex) { Record("rest/spec-multi-turn", "Multi-Turn", false, ex.Message, sw.ElapsedMilliseconds); }

// 12. spec-task-cancel via REST — cancel a running task via streaming
try
{
    sw.Restart();
    var cancelBody = JsonSerializer.Serialize(new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "task-cancel" } } }
    });
    var cancelStreamReq = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec/v1/message:stream")
    {
        Content = new StringContent(cancelBody, Encoding.UTF8, "application/json")
    };
    cancelStreamReq.Headers.Add("A2A-Version", "1.0");
    cancelStreamReq.Headers.Add("Accept", "text/event-stream");

    string? restCancelTaskId = null;
    using var restStreamCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    var cancelStreamResp = await http.SendAsync(cancelStreamReq, HttpCompletionOption.ResponseHeadersRead, restStreamCts.Token);
    using var cancelStream = await cancelStreamResp.Content.ReadAsStreamAsync();
    using var cancelReader = new StreamReader(cancelStream);
    while (await cancelReader.ReadLineAsync() is { } line)
    {
        if (!line.StartsWith("data:")) continue;
        var evJson = JsonNode.Parse(line["data:".Length..]);
        restCancelTaskId = evJson?["task"]?["id"]?.GetValue<string>()
                        ?? evJson?["statusUpdate"]?["taskId"]?.GetValue<string>()
                        ?? evJson?["artifactUpdate"]?["taskId"]?.GetValue<string>();
        if (restCancelTaskId is not null) break;
    }

    if (restCancelTaskId is null)
    {
        Record("rest/spec-task-cancel", "Task Cancel", false, "no taskId from stream", sw.ElapsedMilliseconds);
    }
    else
    {
        var cancelResp = await RestPost($"{baseUrl}/spec/v1/tasks/{restCancelTaskId}:cancel", new { });
        var cancelJson = JsonNode.Parse(await cancelResp.Content.ReadAsStringAsync());
        var cancelState = cancelJson?["status"]?["state"]?.GetValue<string>();
        Record("rest/spec-task-cancel", "Task Cancel", cancelState == "TASK_STATE_CANCELED",
            $"state={cancelState}", sw.ElapsedMilliseconds);
    }
}
catch (OperationCanceledException) { Record("rest/spec-task-cancel", "Task Cancel", false, "streaming timed out before taskId", sw.ElapsedMilliseconds); }
catch (Exception ex) { Record("rest/spec-task-cancel", "Task Cancel", false, ex.Message, sw.ElapsedMilliseconds); }

// 13. spec-list-tasks via REST — list tasks
try
{
    sw.Restart();
    var listResp = await RestGet($"{baseUrl}/spec/v1/tasks");
    var listJson = JsonNode.Parse(await listResp.Content.ReadAsStringAsync());
    var tasks = listJson?["tasks"] as JsonArray;
    Record("rest/spec-list-tasks", "List Tasks", listResp.IsSuccessStatusCode && (tasks?.Count ?? 0) >= 1,
        $"status={listResp.StatusCode}, count={tasks?.Count}", sw.ElapsedMilliseconds);
}
catch (Exception ex) { Record("rest/spec-list-tasks", "List Tasks", false, ex.Message, sw.ElapsedMilliseconds); }

// 14. spec-return-immediately via REST — test returnImmediately flag (expected to fail)
try
{
    sw.Restart();
    var riRestClient = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
    var riRestBody = JsonSerializer.Serialize(new
    {
        message = new { messageId = Guid.NewGuid().ToString("N"), role = "ROLE_USER",
            parts = new[] { new { text = "long-running test" } } },
        configuration = new { returnImmediately = true }
    });
    var riRestReq = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl}/spec/v1/message:send")
    {
        Content = new StringContent(riRestBody, Encoding.UTF8, "application/json")
    };
    riRestReq.Headers.Add("A2A-Version", "1.0");
    var riRestSw = Stopwatch.StartNew();
    var riRestResp = await riRestClient.SendAsync(riRestReq);
    riRestSw.Stop();
    var riRestJson = JsonNode.Parse(await riRestResp.Content.ReadAsStringAsync());
    var riRestState = riRestJson?["task"]?["status"]?["state"]?.GetValue<string>();
    bool riRestPassed = riRestSw.ElapsedMilliseconds < 2000 && riRestState == "TASK_STATE_WORKING";
    string riRestDetail = riRestPassed
        ? $"state={riRestState}, time={riRestSw.ElapsedMilliseconds}ms"
        : $"returnImmediately ignored by SDK — state={riRestState}, time={riRestSw.ElapsedMilliseconds}ms";
    Record("rest/spec-return-immediately", "Return Immediately", riRestPassed, riRestDetail, sw.ElapsedMilliseconds);
    riRestClient.Dispose();
}
catch (Exception ex) { Record("rest/spec-return-immediately", "Return Immediately", false, ex.Message, sw.ElapsedMilliseconds); }

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
