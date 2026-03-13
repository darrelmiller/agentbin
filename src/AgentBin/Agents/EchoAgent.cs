using A2A;
using A2A.AspNetCore;

namespace AgentBin.Agents;

/// <summary>
/// Simple message-only echo agent. Returns the user's message prefixed with "Echo: ".
/// Validates multi-agent hosting and provides a baseline sanity check for A2A clients.
/// </summary>
public sealed class EchoAgent : IAgentHandler
{
    public async Task ExecuteAsync(RequestContext context, AgentEventQueue eventQueue, CancellationToken cancellationToken)
    {
        var responder = new MessageResponder(eventQueue, context.ContextId);
        var text = context.UserText ?? "(empty message)";
        await responder.ReplyAsync($"Echo: {text}", cancellationToken);
    }

    public static AgentCard GetAgentCard(string agentUrl) =>
        new()
        {
            Name = "Echo Agent",
            Description = "A simple echo agent that returns your message. Use this to verify basic A2A connectivity.",
            Version = "1.0.0",
            SupportedInterfaces =
            [
                new AgentInterface
                {
                    Url = agentUrl,
                    ProtocolBinding = "JSONRPC",
                    ProtocolVersion = "1.0",
                }
            ],
            DefaultInputModes = ["text/plain"],
            DefaultOutputModes = ["text/plain"],
            Capabilities = new AgentCapabilities { Streaming = false, PushNotifications = false },
            Skills =
            [
                new AgentSkill
                {
                    Id = "echo",
                    Name = "Echo",
                    Description = "Echoes back the user message.",
                    Tags = ["echo", "test"],
                }
            ],
        };
}
