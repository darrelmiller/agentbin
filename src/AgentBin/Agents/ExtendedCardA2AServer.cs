using A2A;
using A2A.AspNetCore;

namespace AgentBin.Agents;

/// <summary>
/// Custom A2AServer that supports extended agent cards with bearer token authentication.
/// Overrides GetExtendedAgentCardAsync to check for a known bearer token and return
/// an extended card with additional skills visible only to authenticated clients.
/// </summary>
public sealed class ExtendedCardA2AServer : A2AServer
{
    private readonly AgentCard _extendedCard;
    private readonly IHttpContextAccessor _httpContextAccessor;
    internal const string ExpectedToken = "agentbin-test-token";

    public ExtendedCardA2AServer(
        IAgentHandler handler,
        ITaskStore taskStore,
        ChannelEventNotifier notifier,
        ILogger<A2AServer> logger,
        IHttpContextAccessor httpContextAccessor,
        AgentCard extendedCard)
        : base(handler, taskStore, notifier, logger)
    {
        _httpContextAccessor = httpContextAccessor;
        _extendedCard = extendedCard;
    }

    public override Task<AgentCard> GetExtendedAgentCardAsync(
        GetExtendedAgentCardRequest request,
        CancellationToken cancellationToken = default)
    {
        var context = _httpContextAccessor.HttpContext;
        var authHeader = context?.Request.Headers.Authorization.FirstOrDefault();

        if (string.IsNullOrEmpty(authHeader) ||
            !authHeader.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase) ||
            authHeader["Bearer ".Length..].Trim() != ExpectedToken)
        {
            throw new A2AException(
                "Authentication required for extended agent card.",
                A2AErrorCode.InvalidRequest);
        }

        return Task.FromResult(_extendedCard);
    }
}
