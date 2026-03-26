using A2A;
using A2A.AspNetCore;
using AgentBin.Agents;
using AgentBin.V03Compat;
using Microsoft.Extensions.Logging;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);

// Serialize nulls as absent — matches A2A SDK conventions and TCK schema expectations
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull;
});

// CORS — allow any origin (public test bed for browser-based A2A clients)
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.AllowAnyOrigin()
              .AllowAnyMethod()
              .AllowAnyHeader()
              .WithExposedHeaders("A2A-Version"));
});

// Determine base URL from environment or listening URL
var baseUrl = builder.Configuration["BASE_URL"]
    ?? builder.Configuration["urls"]?.Split(';').FirstOrDefault()
    ?? Environment.GetEnvironmentVariable("ASPNETCORE_URLS")?.Split(';').FirstOrDefault()
    ?? "http://localhost:5000";

// Register the SpecAgent via the easy-path DI pattern
var specCard = SpecAgent.GetAgentCard($"{baseUrl}/spec");
builder.Services.AddA2AAgent<SpecAgent>(specCard);

var app = builder.Build();

// v0.3 translation middleware — must be before MapA2A endpoints.
// Intercepts POST requests without A2A-Version header and translates v0.3 ↔ v1.0.
app.UseMiddleware<V03TranslationMiddleware>();
app.UseCors();

// Add caching headers to agent card responses (both .well-known and base URL GET)
var agentCardPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "/spec", "/echo", "/spec03" };
app.Use(async (context, next) =>
{
    if (context.Request.Method == "GET" &&
        (context.Request.Path.Value?.EndsWith("/.well-known/agent-card.json") == true ||
         agentCardPaths.Contains(context.Request.Path.Value ?? "")))
    {
        context.Response.OnStarting(() =>
        {
            AddCardCacheHeaders(context.Response);
            return System.Threading.Tasks.Task.CompletedTask;
        });
    }
    await next();
});

// Health check
app.MapGet("/health", () => Results.Ok(new { Status = "Healthy", Timestamp = DateTimeOffset.UtcNow }));

// Map SpecAgent (uses DI-registered handler)
app.MapA2A("/spec");

// Map SpecAgent REST binding (HTTP+JSON)
var specHandler = app.Services.GetRequiredService<IA2ARequestHandler>();
app.MapHttpA2A(specHandler, specCard, "/spec");

// Map EchoAgent manually (second agent — can't use AddA2AAgent twice)
var echoCard = EchoAgent.GetAgentCard($"{baseUrl}/echo");
var echoServer = new A2AServer(
    new EchoAgent(),
    new InMemoryTaskStore(),
    new ChannelEventNotifier(),
    app.Services.GetRequiredService<ILogger<A2AServer>>());
app.MapA2A(echoServer, "/echo");
app.MapHttpA2A(echoServer, echoCard, "/echo");

// Base-URL GET returns the agent card (future A2A proposal: GET on agent URL serves its card)
app.MapGet("/echo/.well-known/agent-card.json", () => Results.Ok(echoCard));
app.MapGet("/echo", () => Results.Ok(echoCard));

// Map Spec v0.3 agent — same handler, but serves a v0.3-format agent card.
// Clients discovering this agent should see protocolVersion "0.3.0" and fall back.
var spec03Card = SpecAgent.GetV03AgentCard($"{baseUrl}/spec03");
var spec03Server = new A2AServer(
    new SpecAgent(),
    new InMemoryTaskStore(),
    new ChannelEventNotifier(),
    app.Services.GetRequiredService<ILogger<A2AServer>>());
app.MapA2A(spec03Server, "/spec03");
app.MapGet("/spec03/.well-known/agent-card.json", () => Results.Ok(spec03Card));
app.MapGet("/spec03", () => Results.Ok(spec03Card));

// Base-URL GET for spec agent — MapA2A registers .well-known but not the bare GET
app.MapGet("/spec", () => Results.Ok(specCard));

// Root-level agent card — many SDKs discover agents at /.well-known/agent-card.json on the domain root.
// Returns the Spec agent's card (primary agent); URLs still point to /spec/ endpoints.
app.MapGet("/.well-known/agent-card.json", () => Results.Ok(specCard));

app.Run();

static void AddCardCacheHeaders(HttpResponse response)
{
    response.Headers["Cache-Control"] = "public, max-age=3600";
    response.Headers["ETag"] = $"\"{typeof(SpecAgent).Assembly.GetName().Version}\"";
    response.Headers["Last-Modified"] = new DateTimeOffset(2025, 1, 1, 0, 0, 0, TimeSpan.Zero).ToString("R");
}
