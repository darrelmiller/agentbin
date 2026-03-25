using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using A2A;
using A2A.AspNetCore;

namespace AgentBin.V03Compat;

/// <summary>
/// Middleware that detects v0.3 clients (no A2A-Version header) and translates
/// requests/responses between v0.3 and v1.0 JSON-RPC format.
/// Wraps the standard MapA2A endpoints rather than calling the internal processor directly.
/// </summary>
public sealed class V03TranslationMiddleware
{
    private readonly RequestDelegate _next;

    public V03TranslationMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var hasVersionHeader = !string.IsNullOrEmpty(context.Request.Headers["A2A-Version"].FirstOrDefault());

        // V0.3 agent card translation is no longer needed for GET requests.
        // Root /.well-known/agent-card.json was removed (non-standard).
        // /spec, /echo, /spec03 all serve their own cards directly.

        // Only intercept POST requests to A2A endpoints without A2A-Version header
        if (context.Request.Method != "POST" || hasVersionHeader)
        {
            await _next(context);
            return;
        }

        // Read the original v0.3 request body
        context.Request.EnableBuffering();
        using var reader = new StreamReader(context.Request.Body, Encoding.UTF8, leaveOpen: true);
        var rawBody = await reader.ReadToEndAsync();
        context.Request.Body.Position = 0;

        // Try to parse as JSON-RPC and check if it uses v0.3 method names
        JsonNode? requestNode;
        try
        {
            requestNode = JsonNode.Parse(rawBody);
        }
        catch
        {
            // Not valid JSON — let the v1.0 processor handle the error
            await _next(context);
            return;
        }

        if (requestNode is null)
        {
            await _next(context);
            return;
        }

        var method = requestNode["method"]?.GetValue<string>() ?? "";
        var isV03Method = method.Contains('/'); // v0.3 uses slash-separated methods like "message/send"
        if (!isV03Method)
        {
            // Already a v1.0 method name — pass through (client just forgot the header)
            await _next(context);
            return;
        }

        var isStreaming = method is "message/stream";

        // Translate v0.3 → v1.0 request
        V03Translator.TranslateRequestToV1(requestNode);

        // Replace request body with translated JSON
        var translatedBytes = Encoding.UTF8.GetBytes(requestNode.ToJsonString());
        context.Request.Body = new MemoryStream(translatedBytes);
        context.Request.ContentLength = translatedBytes.Length;

        // Set A2A-Version header so the v1.0 processor accepts it
        context.Request.Headers["A2A-Version"] = "1.0";

        // Capture the response to translate it back to v0.3
        var originalBody = context.Response.Body;
        using var responseBuffer = new MemoryStream();
        context.Response.Body = responseBuffer;

        await _next(context);

        responseBuffer.Position = 0;
        var responseContent = Encoding.UTF8.GetString(responseBuffer.ToArray());

        // Translate v1.0 → v0.3 response
        string translatedResponse;
        if (isStreaming && context.Response.ContentType?.Contains("text/event-stream") == true)
        {
            translatedResponse = TranslateSseContent(responseContent);
        }
        else
        {
            translatedResponse = TranslateJsonResponse(responseContent);
        }

        context.Response.Body = originalBody;
        var responseBytes = Encoding.UTF8.GetBytes(translatedResponse);
        context.Response.ContentLength = responseBytes.Length;
        await context.Response.Body.WriteAsync(responseBytes);
    }

    private static string TranslateJsonResponse(string json)
    {
        try
        {
            var node = JsonNode.Parse(json);
            if (node is null) return json;
            V03Translator.TranslateResponseToV03(node);
            return node.ToJsonString();
        }
        catch
        {
            return json;
        }
    }

    private async Task TranslateAgentCardResponse(HttpContext context)
    {
        // Set A2A-Version so MapA2A serves the v1.0 card
        context.Request.Headers["A2A-Version"] = "1.0";

        var originalBody = context.Response.Body;
        using var responseBuffer = new MemoryStream();
        context.Response.Body = responseBuffer;

        await _next(context);

        responseBuffer.Position = 0;
        var v1Json = Encoding.UTF8.GetString(responseBuffer.ToArray());

        // Translate to v0.3 format
        string v03Json;
        try
        {
            var node = JsonNode.Parse(v1Json);
            if (node is JsonObject cardObj)
            {
                v03Json = TranslateAgentCardToV03(cardObj);
            }
            else
            {
                v03Json = v1Json;
            }
        }
        catch
        {
            v03Json = v1Json;
        }

        context.Response.Body = originalBody;
        var bytes = Encoding.UTF8.GetBytes(v03Json);
        context.Response.ContentLength = bytes.Length;
        await context.Response.Body.WriteAsync(bytes);
    }

    private static string TranslateAgentCardToV03(JsonObject card)
    {
        var v03 = new JsonObject();

        CopyIfPresent(card, v03, "name");
        CopyIfPresent(card, v03, "description");
        CopyIfPresent(card, v03, "version");
        CopyIfPresent(card, v03, "iconUrl");
        CopyIfPresent(card, v03, "documentationUrl");

        // Extract url from supportedInterfaces[0]
        if (card["supportedInterfaces"] is JsonArray interfaces && interfaces.Count > 0 &&
            interfaces[0] is JsonObject iface && iface["url"] is not null)
        {
            v03["url"] = iface["url"]!.DeepClone();
        }

        v03["protocolVersion"] = "0.3.0";

        // Translate provider
        if (card["provider"] is JsonObject provider)
        {
            var v03Provider = new JsonObject();
            if (provider["organization"] is not null)
                v03Provider["name"] = provider["organization"]!.DeepClone();
            CopyIfPresent(provider, v03Provider, "url");
            v03["provider"] = v03Provider;
        }

        CopyIfPresent(card, v03, "defaultInputModes");
        CopyIfPresent(card, v03, "defaultOutputModes");

        // Translate capabilities
        var caps = new JsonObject();
        if (card["capabilities"] is JsonObject cardCaps)
        {
            caps["supportsStreaming"] = cardCaps["streaming"]?.GetValue<bool>() ?? false;
            caps["supportsPushNotifications"] = cardCaps["pushNotifications"]?.GetValue<bool>() ?? false;
        }
        v03["capabilities"] = caps;

        // Copy skills
        CopyIfPresent(card, v03, "skills");

        return v03.ToJsonString();
    }

    private static void CopyIfPresent(JsonObject source, JsonObject target, string key)
    {
        if (source[key] is not null)
            target[key] = source[key]!.DeepClone();
    }

    private static string TranslateSseContent(string sseContent)
    {
        var sb = new StringBuilder();
        foreach (var line in sseContent.Split('\n'))
        {
            if (line.StartsWith("data: "))
            {
                var data = line[6..].TrimEnd('\r');
                var translated = V03Translator.TranslateSseEventToV03(data);
                sb.Append("data: ").Append(translated).Append('\n');
            }
            else
            {
                sb.Append(line).Append('\n');
            }
        }
        return sb.ToString();
    }
}
