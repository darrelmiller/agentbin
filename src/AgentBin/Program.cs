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

// Register IHttpContextAccessor for extended card auth checks
builder.Services.AddHttpContextAccessor();

// Determine base URL from environment or listening URL
var baseUrl = builder.Configuration["BASE_URL"]
    ?? builder.Configuration["urls"]?.Split(';').FirstOrDefault()
    ?? Environment.GetEnvironmentVariable("ASPNETCORE_URLS")?.Split(';').FirstOrDefault()
    ?? "http://localhost:5000";

// Register the SpecAgent card (used for discovery endpoints)
var specCard = SpecAgent.GetAgentCard($"{baseUrl}/spec");

var app = builder.Build();

// v0.3 translation middleware — must be before MapA2A endpoints.
// Intercepts POST requests without A2A-Version header and translates v0.3 ↔ v1.0.
app.UseMiddleware<V03TranslationMiddleware>();
app.UseCors();

// Protect REST extended agent card endpoints — returns 401 for unauthenticated requests
app.Use(async (context, next) =>
{
    if (context.Request.Method == "GET" &&
        context.Request.Path.Value?.EndsWith("/extendedAgentCard", StringComparison.OrdinalIgnoreCase) == true)
    {
        var auth = context.Request.Headers.Authorization.FirstOrDefault();
        if (string.IsNullOrEmpty(auth) ||
            !auth.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase) ||
            auth["Bearer ".Length..].Trim() != ExtendedCardA2AServer.ExpectedToken)
        {
            context.Response.StatusCode = 401;
            context.Response.Headers.WWWAuthenticate = "Bearer";
            return;
        }
    }
    await next();
});

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

// Map SpecAgent with extended card support (manual creation for auth override)
var extendedCard = SpecAgent.GetExtendedAgentCard($"{baseUrl}/spec");
var specServer = new ExtendedCardA2AServer(
    new SpecAgent(),
    new InMemoryTaskStore(),
    new ChannelEventNotifier(),
    app.Services.GetRequiredService<ILogger<A2AServer>>(),
    app.Services.GetRequiredService<IHttpContextAccessor>(),
    extendedCard);

// Map SpecAgent (JSON-RPC)
app.MapA2A(specServer, "/spec");

// Map SpecAgent REST binding (HTTP+JSON)
app.MapHttpA2A(specServer, specCard, "/spec");

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

// Base-URL GET and .well-known for spec agent
// (MapA2A no longer registers .well-known as of PR#339)
app.MapGet("/spec/.well-known/agent-card.json", () => Results.Ok(specCard));
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
