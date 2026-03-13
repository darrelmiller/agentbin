using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentBin.V03Compat;

/// <summary>
/// Translates between A2A v0.3 and v1.0 JSON-RPC wire formats.
/// v0.3 uses kebab-case method names, kebab-case enums, and "kind" discriminators.
/// v1.0 uses PascalCase methods, SCREAMING_SNAKE_CASE enums, and field-presence (oneof).
/// </summary>
public static class V03Translator
{
    // v0.3 → v1.0 method name mapping
    private static readonly Dictionary<string, string> MethodToV1 = new(StringComparer.OrdinalIgnoreCase)
    {
        ["message/send"] = "SendMessage",
        ["message/stream"] = "SendStreamingMessage",
        ["tasks/get"] = "GetTask",
        ["tasks/cancel"] = "CancelTask",
        ["tasks/resubscribe"] = "SubscribeToTask",
        ["tasks/pushNotificationConfig/set"] = "CreateTaskPushNotificationConfig",
        ["tasks/pushNotificationConfig/get"] = "GetTaskPushNotificationConfig",
    };

    // v1.0 → v0.3 method name mapping (reverse)
    private static readonly Dictionary<string, string> MethodToV03 =
        MethodToV1.ToDictionary(kvp => kvp.Value, kvp => kvp.Key, StringComparer.OrdinalIgnoreCase);

    // Role mapping
    private static readonly Dictionary<string, string> RoleToV1 = new(StringComparer.OrdinalIgnoreCase)
    {
        ["user"] = "ROLE_USER",
        ["agent"] = "ROLE_AGENT",
    };

    private static readonly Dictionary<string, string> RoleToV03 = new(StringComparer.OrdinalIgnoreCase)
    {
        ["ROLE_USER"] = "user",
        ["ROLE_AGENT"] = "agent",
        ["ROLE_UNSPECIFIED"] = "user",
    };

    // Task state mapping
    private static readonly Dictionary<string, string> StateToV1 = new(StringComparer.OrdinalIgnoreCase)
    {
        ["submitted"] = "TASK_STATE_SUBMITTED",
        ["working"] = "TASK_STATE_WORKING",
        ["completed"] = "TASK_STATE_COMPLETED",
        ["failed"] = "TASK_STATE_FAILED",
        ["canceled"] = "TASK_STATE_CANCELED",
        ["input-required"] = "TASK_STATE_INPUT_REQUIRED",
        ["rejected"] = "TASK_STATE_REJECTED",
        ["auth-required"] = "TASK_STATE_AUTH_REQUIRED",
    };

    private static readonly Dictionary<string, string> StateToV03 =
        StateToV1.ToDictionary(kvp => kvp.Value, kvp => kvp.Key, StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// Translates a v0.3 JSON-RPC request body to v1.0 format.
    /// </summary>
    public static JsonNode TranslateRequestToV1(JsonNode root)
    {
        // Translate method name
        if (root["method"] is JsonValue methodVal)
        {
            var method = methodVal.GetValue<string>();
            if (MethodToV1.TryGetValue(method, out var v1Method))
                root["method"] = v1Method;
        }

        // Translate params
        if (root["params"] is JsonObject paramsObj)
        {
            TranslateParamsToV1(paramsObj);
        }

        return root;
    }

    /// <summary>
    /// Translates a v1.0 JSON-RPC response body to v0.3 format.
    /// </summary>
    public static JsonNode TranslateResponseToV03(JsonNode root)
    {
        if (root["result"] is JsonNode result)
        {
            root["result"] = TranslateResultToV03(result);
        }

        return root;
    }

    /// <summary>
    /// Translates a v1.0 SSE event line to v0.3 format.
    /// </summary>
    public static string TranslateSseEventToV03(string eventData)
    {
        try
        {
            var node = JsonNode.Parse(eventData);
            if (node is null) return eventData;
            TranslateResponseToV03(node);
            return node.ToJsonString();
        }
        catch
        {
            return eventData;
        }
    }

    private static void TranslateParamsToV1(JsonObject paramsObj)
    {
        // Translate message within params
        if (paramsObj["message"] is JsonObject messageObj)
        {
            TranslateMessageToV1(messageObj);
        }

        // For tasks/get: params has "id" field — same in both versions
        // For tasks/cancel: params has "id" field — same in both versions
    }

    private static void TranslateMessageToV1(JsonObject msg)
    {
        // Remove "kind" discriminator (v0.3 has it, v1.0 doesn't)
        msg.Remove("kind");

        // Translate role
        if (msg["role"] is JsonValue roleVal)
        {
            var role = roleVal.GetValue<string>();
            if (RoleToV1.TryGetValue(role, out var v1Role))
                msg["role"] = v1Role;
        }

        // Translate parts
        if (msg["parts"] is JsonArray partsArr)
        {
            for (int i = 0; i < partsArr.Count; i++)
            {
                if (partsArr[i] is JsonObject partObj)
                {
                    partsArr[i] = TranslatePartToV1(partObj);
                }
            }
        }
    }

    private static JsonNode TranslatePartToV1(JsonObject part)
    {
        var kind = part["kind"]?.GetValue<string>();
        var result = new JsonObject();

        // Copy metadata, filename if present
        CopyIfPresent(part, result, "metadata");

        switch (kind)
        {
            case "text":
                CopyIfPresent(part, result, "text");
                break;

            case "file":
                // v0.3: { kind: "file", file: { uri: "...", mimeType: "...", bytes: "...", name: "..." } }
                // v1.0: { url: "...", mediaType: "...", filename: "..." } or { raw: bytes, mediaType: "..." }
                if (part["file"] is JsonObject fileObj)
                {
                    if (fileObj["uri"] is not null)
                        result["url"] = fileObj["uri"]!.DeepClone();
                    if (fileObj["bytes"] is not null)
                        result["raw"] = fileObj["bytes"]!.DeepClone();
                    if (fileObj["mimeType"] is not null)
                        result["mediaType"] = fileObj["mimeType"]!.DeepClone();
                    if (fileObj["name"] is not null)
                        result["filename"] = fileObj["name"]!.DeepClone();
                }
                break;

            case "data":
                CopyIfPresent(part, result, "data");
                break;

            default:
                // Unknown kind — pass through without kind field
                foreach (var prop in part)
                {
                    if (prop.Key != "kind")
                        result[prop.Key] = prop.Value?.DeepClone();
                }
                break;
        }

        return result;
    }

    private static JsonNode TranslateResultToV03(JsonNode result)
    {
        // v1.0 result can be:
        // { "message": { ... } } — message response
        // { "task": { ... } } — task response
        // or a direct task object for GetTask/CancelTask

        if (result is JsonObject resultObj)
        {
            // SendMessage response: { message: {...} } or { task: {...} }
            if (resultObj["message"] is JsonObject msgObj)
            {
                var v03Msg = TranslateMessageToV03(msgObj);
                v03Msg["kind"] = "message";
                return v03Msg;
            }

            if (resultObj["task"] is JsonObject taskObj)
            {
                return TranslateTaskToV03(taskObj);
            }

            // Direct task response (from GetTask, CancelTask)
            if (resultObj["id"] is not null && resultObj["status"] is not null)
            {
                return TranslateTaskToV03(resultObj);
            }

            // Streaming events: statusUpdate or artifactUpdate (camelCase in v1.0)
            if (resultObj["statusUpdate"] is JsonObject statusUpdate)
            {
                return TranslateStatusUpdateToV03(statusUpdate);
            }

            if (resultObj["artifactUpdate"] is JsonObject artifactUpdate)
            {
                return TranslateArtifactUpdateToV03(artifactUpdate);
            }
        }

        return result;
    }

    private static JsonObject TranslateMessageToV03(JsonObject msg)
    {
        var result = new JsonObject();

        foreach (var prop in msg)
        {
            result[prop.Key] = prop.Value?.DeepClone();
        }

        // Translate role
        if (result["role"] is JsonValue roleVal)
        {
            var role = roleVal.GetValue<string>();
            if (RoleToV03.TryGetValue(role, out var v03Role))
                result["role"] = v03Role;
        }

        // Translate parts
        if (result["parts"] is JsonArray partsArr)
        {
            for (int i = 0; i < partsArr.Count; i++)
            {
                if (partsArr[i] is JsonObject partObj)
                {
                    partsArr[i] = TranslatePartToV03(partObj);
                }
            }
        }

        return result;
    }

    private static JsonObject TranslateTaskToV03(JsonObject task)
    {
        var result = new JsonObject { ["kind"] = "task" };

        foreach (var prop in task)
        {
            result[prop.Key] = prop.Value?.DeepClone();
        }

        // Translate status.state
        TranslateStatusStateToV03(result);

        // Translate status.message
        if (result["status"] is JsonObject statusObj && statusObj["message"] is JsonObject statusMsg)
        {
            statusObj["message"] = TranslateMessageToV03(statusMsg);
        }

        // Translate history messages
        if (result["history"] is JsonArray historyArr)
        {
            for (int i = 0; i < historyArr.Count; i++)
            {
                if (historyArr[i] is JsonObject histMsg)
                {
                    var translated = TranslateMessageToV03(histMsg);
                    translated["kind"] = "message";
                    historyArr[i] = translated;
                }
            }
        }

        // Translate artifact parts
        if (result["artifacts"] is JsonArray artifactsArr)
        {
            foreach (var artifact in artifactsArr)
            {
                if (artifact is JsonObject artObj && artObj["parts"] is JsonArray artParts)
                {
                    for (int i = 0; i < artParts.Count; i++)
                    {
                        if (artParts[i] is JsonObject partObj)
                        {
                            artParts[i] = TranslatePartToV03(partObj);
                        }
                    }
                }
            }
        }

        return result;
    }

    private static JsonObject TranslateStatusUpdateToV03(JsonObject update)
    {
        var result = new JsonObject { ["kind"] = "status-update" };

        foreach (var prop in update)
        {
            result[prop.Key] = prop.Value?.DeepClone();
        }

        TranslateStatusStateToV03(result);

        if (result["status"] is JsonObject statusObj && statusObj["message"] is JsonObject statusMsg)
        {
            statusObj["message"] = TranslateMessageToV03(statusMsg);
        }

        return result;
    }

    private static JsonObject TranslateArtifactUpdateToV03(JsonObject update)
    {
        var result = new JsonObject { ["kind"] = "artifact-update" };

        foreach (var prop in update)
        {
            result[prop.Key] = prop.Value?.DeepClone();
        }

        // Translate artifact parts
        if (result["artifact"] is JsonObject artObj && artObj["parts"] is JsonArray artParts)
        {
            for (int i = 0; i < artParts.Count; i++)
            {
                if (artParts[i] is JsonObject partObj)
                {
                    artParts[i] = TranslatePartToV03(partObj);
                }
            }
        }

        return result;
    }

    private static JsonNode TranslatePartToV03(JsonObject part)
    {
        var result = new JsonObject();

        if (part["text"] is not null)
        {
            result["kind"] = "text";
            result["text"] = part["text"]!.DeepClone();
            CopyIfPresent(part, result, "metadata");
        }
        else if (part["url"] is not null || part["raw"] is not null)
        {
            result["kind"] = "file";
            var fileObj = new JsonObject();
            if (part["url"] is not null)
                fileObj["uri"] = part["url"]!.DeepClone();
            if (part["raw"] is not null)
                fileObj["bytes"] = part["raw"]!.DeepClone();
            if (part["mediaType"] is not null)
                fileObj["mimeType"] = part["mediaType"]!.DeepClone();
            if (part["filename"] is not null)
                fileObj["name"] = part["filename"]!.DeepClone();
            result["file"] = fileObj;
            CopyIfPresent(part, result, "metadata");
        }
        else if (part["data"] is not null)
        {
            result["kind"] = "data";
            result["data"] = part["data"]!.DeepClone();
            CopyIfPresent(part, result, "metadata");
        }
        else
        {
            // Unknown format — pass through
            foreach (var prop in part)
                result[prop.Key] = prop.Value?.DeepClone();
        }

        return result;
    }

    private static void TranslateStatusStateToV03(JsonObject container)
    {
        if (container["status"] is JsonObject statusObj && statusObj["state"] is JsonValue stateVal)
        {
            var state = stateVal.GetValue<string>();
            if (StateToV03.TryGetValue(state, out var v03State))
                statusObj["state"] = v03State;
        }
    }

    private static void CopyIfPresent(JsonObject source, JsonObject target, string key)
    {
        if (source[key] is not null)
            target[key] = source[key]!.DeepClone();
    }
}
