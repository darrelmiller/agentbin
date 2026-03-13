using A2A;
using A2A.AspNetCore;
using AgentBin.Agents;
using Microsoft.Extensions.Logging;

var builder = WebApplication.CreateBuilder(args);

// Determine base URL from environment or default
var baseUrl = builder.Configuration["BASE_URL"] ?? "http://localhost:5000";

// Register the SpecAgent via the easy-path DI pattern
var specCard = SpecAgent.GetAgentCard($"{baseUrl}/spec");
builder.Services.AddA2AAgent<SpecAgent>(specCard);

var app = builder.Build();

// Health check
app.MapGet("/health", () => Results.Ok(new { Status = "Healthy", Timestamp = DateTimeOffset.UtcNow }));

// Map SpecAgent (uses DI-registered handler)
app.MapA2A("/spec");

// Map EchoAgent manually (second agent — can't use AddA2AAgent twice)
var echoCard = EchoAgent.GetAgentCard($"{baseUrl}/echo");
var echoHandler = new EchoAgent();
var echoServer = new A2AServer(
    echoHandler,
    new InMemoryTaskStore(),
    new ChannelEventNotifier(),
    app.Services.GetRequiredService<ILogger<A2AServer>>());
app.MapA2A(echoServer, "/echo");
app.MapWellKnownAgentCard(echoCard, "/echo");

// Root agent card listing
app.MapGet("/.well-known/agent-card.json", () => Results.Ok(new[] { specCard, echoCard }));

app.Run();
