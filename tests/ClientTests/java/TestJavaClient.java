import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Single-file Java A2A client test suite against deployed agentbin service.
 * Uses java.net.http.HttpClient (Java 21+) — no build system or external deps needed.
 *
 * Usage: java TestJavaClient.java [baseUrl]
 *
 * Runs 10 standard A2A protocol compliance tests, prints [PASS]/[FAIL] to stdout,
 * and writes results.json to the same directory as this source file.
 */
public class TestJavaClient {

    static final String DEFAULT_BASE_URL =
            "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";

    static final String A2A_VERSION = "1.0";

    static final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    // Accumulated test results
    static final List<TestResult> results = new ArrayList<>();

    // Shared state: taskId captured from spec-task-lifecycle for reuse in spec-get-task
    static String capturedTaskId = null;
    static String capturedRestTaskId = null;

    record TestResult(String id, String name, boolean passed, String detail, long durationMs) {}

    // ─────────────────────────── main ───────────────────────────

    public static void main(String[] args) throws Exception {
        String baseUrl = args.length > 0 ? args[0] : DEFAULT_BASE_URL;
        // Strip trailing slash
        if (baseUrl.endsWith("/")) baseUrl = baseUrl.substring(0, baseUrl.length() - 1);

        System.out.println("=== Java A2A Client Test Suite ===");
        System.out.println("Target: " + baseUrl);
        System.out.println("Protocol: A2A v" + A2A_VERSION);
        System.out.println();

        // JSON-RPC binding tests
        System.out.println("── JSON-RPC Binding ──");

        // 1. Agent card tests
        testAgentCardEcho(baseUrl);
        testAgentCardSpec(baseUrl);

        // 2. Echo agent
        testEchoSendMessage(baseUrl);

        // 3. Spec agent skills
        testSpecMessageOnly(baseUrl);
        testSpecTaskLifecycle(baseUrl);
        testSpecGetTask(baseUrl);
        testSpecTaskFailure(baseUrl);
        testSpecDataTypes(baseUrl);
        testSpecStreaming(baseUrl);

        // 4. Error cases
        testErrorTaskNotFound(baseUrl);

        // 5. Extended tests
        testSpecMultiTurn(baseUrl);
        testSpecTaskCancel(baseUrl);
        testSpecListTasks(baseUrl);
        testSpecReturnImmediately(baseUrl);

        // REST binding tests
        System.out.println("\n── HTTP+JSON REST Binding ──");
        testRestAgentCardEcho(baseUrl);
        testRestAgentCardSpec(baseUrl);
        testRestEchoSendMessage(baseUrl);
        testRestSpecMessageOnly(baseUrl);
        testRestSpecTaskLifecycle(baseUrl);
        testRestSpecGetTask(baseUrl);
        testRestSpecTaskFailure(baseUrl);
        testRestSpecDataTypes(baseUrl);
        testRestSpecStreaming(baseUrl);
        testRestErrorTaskNotFound(baseUrl);

        testRestSpecMultiTurn(baseUrl);
        testRestSpecTaskCancel(baseUrl);
        testRestSpecListTasks(baseUrl);
        testRestSpecReturnImmediately(baseUrl);

        // Summary
        long passCount = results.stream().filter(r -> r.passed).count();
        long failCount = results.stream().filter(r -> !r.passed).count();
        System.out.println();
        System.out.printf("Total: %d passed, %d failed, %d total%n", passCount, failCount, results.size());

        // Write results.json next to this source file
        writeResultsJson(baseUrl);

        System.exit(failCount > 0 ? 1 : 0);
    }

    // ─────────────────────── Test implementations ───────────────────────

    /** 1. agent-card-echo — Resolve echo agent card */
    static void testAgentCardEcho(String baseUrl) {
        String id = "jsonrpc/agent-card-echo";
        long start = System.nanoTime();
        try {
            String url = baseUrl + "/echo/.well-known/agent-card.json";
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "Echo Agent Card", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            String name = extractJsonString(body, "name");
            boolean hasSkills = body.contains("\"skills\"");
            boolean hasSupported = body.contains("\"supportedInterfaces\"")
                    || body.contains("\"capabilities\"");

            if (name != null && hasSkills) {
                int skillCount = countOccurrences(body, "\"id\"");
                record(id, "Echo Agent Card", true,
                        "name=" + name + ", skills=" + skillCount, ms);
            } else {
                record(id, "Echo Agent Card", false, "Missing name or skills", ms);
            }
        } catch (Exception e) {
            record(id, "Echo Agent Card", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 2. agent-card-spec — Resolve spec agent card */
    static void testAgentCardSpec(String baseUrl) {
        String id = "jsonrpc/agent-card-spec";
        long start = System.nanoTime();
        try {
            String url = baseUrl + "/spec/.well-known/agent-card.json";
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "Spec Agent Card", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            String name = extractJsonString(body, "name");
            boolean hasSkills = body.contains("\"skills\"");

            if (name != null && hasSkills) {
                int skillCount = countOccurrences(body, "\"id\"");
                record(id, "Spec Agent Card", true,
                        "name=" + name + ", skills=" + skillCount, ms);
            } else {
                record(id, "Spec Agent Card", false, "Missing name or skills", ms);
            }
        } catch (Exception e) {
            record(id, "Spec Agent Card", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 3. echo-send-message — Send message to echo agent, verify echo */
    static void testEchoSendMessage(String baseUrl) {
        String id = "jsonrpc/echo-send-message";
        long start = System.nanoTime();
        try {
            String body = sendMessage(baseUrl + "/echo", "hello from Java");
            long ms = elapsed(start);

            if (body == null) {
                record(id, "Echo Send Message", false, "null response", ms);
                return;
            }
            if (hasJsonRpcError(body)) {
                record(id, "Echo Send Message", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }
            String text = extractResponseText(body);
            boolean echoed = text != null && text.toLowerCase().contains("hello from java");
            record(id, "Echo Send Message", echoed,
                    echoed ? "echo=" + truncate(text, 80) : "unexpected: " + truncate(text, 80), ms);
        } catch (Exception e) {
            record(id, "Echo Send Message", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 4. spec-message-only — Message-only skill (returns Message, no Task) */
    static void testSpecMessageOnly(String baseUrl) {
        String id = "jsonrpc/spec-message-only";
        long start = System.nanoTime();
        try {
            String body = sendMessage(baseUrl + "/spec", "message-only hello from Java");
            long ms = elapsed(start);

            if (body == null) {
                record(id, "Spec Message Only", false, "null response", ms);
                return;
            }
            if (hasJsonRpcError(body)) {
                record(id, "Spec Message Only", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }

            // Message-only should return a result with a message (no taskId / no task state)
            boolean hasResult = body.contains("\"result\"");
            String text = extractResponseText(body);
            boolean hasText = text != null && !text.isEmpty();
            // Ideally no task state present (pure message response)
            boolean isMessageOnly = !body.contains("\"TASK_STATE_");

            record(id, "Spec Message Only", hasResult && hasText,
                    "text=" + truncate(text, 60) + ", messageOnly=" + isMessageOnly, ms);
        } catch (Exception e) {
            record(id, "Spec Message Only", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 5. spec-task-lifecycle — Task lifecycle: completed + artifacts */
    static void testSpecTaskLifecycle(String baseUrl) {
        String id = "jsonrpc/spec-task-lifecycle";
        long start = System.nanoTime();
        try {
            String body = sendMessage(baseUrl + "/spec", "task-lifecycle process this");
            long ms = elapsed(start);

            if (body == null) {
                record(id, "Spec Task Lifecycle", false, "null response", ms);
                return;
            }
            if (hasJsonRpcError(body)) {
                record(id, "Spec Task Lifecycle", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }

            boolean completed = body.contains("TASK_STATE_COMPLETED")
                    || body.contains("\"completed\"");
            boolean hasArtifacts = body.contains("\"artifacts\"");

            // Capture taskId for spec-get-task
            // Need to find "id" inside the "task" object, not the top-level JSON-RPC "id"
            int taskIdx = body.indexOf("\"task\"");
            if (taskIdx >= 0) {
                String taskPortion = body.substring(taskIdx);
                capturedTaskId = extractJsonString(taskPortion, "id");
            }
            if (capturedTaskId == null) {
                capturedTaskId = "UNKNOWN";
            }

            String text = extractResponseText(body);
            record(id, "Spec Task Lifecycle", completed && hasArtifacts,
                    "completed=" + completed + ", artifacts=" + hasArtifacts
                            + ", taskId=" + truncate(capturedTaskId, 36)
                            + ", text=" + truncate(text, 40), ms);
        } catch (Exception e) {
            record(id, "Spec Task Lifecycle", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 6. spec-get-task — GetTask retrieves previously created task */
    static void testSpecGetTask(String baseUrl) {
        String id = "jsonrpc/spec-get-task";
        long start = System.nanoTime();
        try {
            if (capturedTaskId == null) {
                record(id, "Spec Get Task", false, "no taskId from lifecycle test", elapsed(start));
                return;
            }

            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "GetTask",
                        "id": "%s",
                        "params": {
                            "id": "%s"
                        }
                    }
                    """.formatted(rpcId, capturedTaskId);

            HttpResponse<String> resp = httpPost(baseUrl + "/spec", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "Spec Get Task", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();
            if (hasJsonRpcError(body)) {
                record(id, "Spec Get Task", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }

            boolean hasResult = body.contains("\"result\"");
            boolean hasTaskId = body.contains(capturedTaskId);
            String state = extractJsonString(body, "state");
            if (state == null) {
                // Try looking for status.state
                state = extractTaskState(body);
            }

            record(id, "Spec Get Task", hasResult && hasTaskId,
                    "found=" + hasTaskId + ", state=" + state, ms);
        } catch (Exception e) {
            record(id, "Spec Get Task", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 7. spec-task-failure — Task transitions to failed state */
    static void testSpecTaskFailure(String baseUrl) {
        String id = "jsonrpc/spec-task-failure";
        long start = System.nanoTime();
        try {
            String body = sendMessage(baseUrl + "/spec", "task-failure trigger error");
            long ms = elapsed(start);

            if (body == null) {
                record(id, "Spec Task Failure", false, "null response", ms);
                return;
            }

            // Could be a JSON-RPC error or a task with TASK_STATE_FAILED
            boolean failed = body.contains("TASK_STATE_FAILED")
                    || body.contains("\"failed\"");

            // If the service returns a JSON-RPC error for failure, that's also acceptable
            if (!failed && hasJsonRpcError(body)) {
                String errMsg = extractJsonString(body, "message");
                failed = errMsg != null;
                record(id, "Spec Task Failure", failed,
                        "error=" + truncate(errMsg, 60), ms);
                return;
            }

            String state = extractTaskState(body);
            record(id, "Spec Task Failure", failed,
                    "state=" + state + ", hasFailed=" + failed, ms);
        } catch (Exception e) {
            record(id, "Spec Task Failure", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 8. spec-data-types — Returns text, data, file parts */
    static void testSpecDataTypes(String baseUrl) {
        String id = "jsonrpc/spec-data-types";
        long start = System.nanoTime();
        try {
            String body = sendMessage(baseUrl + "/spec", "data-types show all");
            long ms = elapsed(start);

            if (body == null) {
                record(id, "Spec Data Types", false, "null response", ms);
                return;
            }
            if (hasJsonRpcError(body)) {
                record(id, "Spec Data Types", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }

            boolean hasText = body.contains("\"text\"");
            boolean hasData = body.contains("\"data\"");
            boolean hasFile = body.contains("\"mediaType\"") || body.contains("\"url\"");

            String detail = "text=" + hasText + ", data=" + hasData + ", file=" + hasFile;
            // At least text + one of data/file
            boolean pass = hasText && (hasData || hasFile);
            record(id, "Spec Data Types", pass, detail, ms);
        } catch (Exception e) {
            record(id, "Spec Data Types", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 9. spec-streaming — SSE streaming with multiple events */
    static void testSpecStreaming(String baseUrl) {
        String id = "jsonrpc/spec-streaming";
        long start = System.nanoTime();
        try {
            String msgId = UUID.randomUUID().toString();
            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "SendStreamingMessage",
                        "id": "%s",
                        "params": {
                            "message": {
                                "messageId": "%s",
                                "role": "ROLE_USER",
                                "parts": [{"text": "streaming generate output"}]
                            }
                        }
                    }
                    """.formatted(rpcId, msgId);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(30))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "Spec Streaming", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();

            // Count SSE data: lines
            int eventCount = 0;
            for (String line : body.split("\n")) {
                if (line.startsWith("data:")) {
                    eventCount++;
                }
            }

            boolean hasEvents = eventCount > 0;
            // Check for completed/final event
            boolean hasCompleted = body.contains("TASK_STATE_COMPLETED")
                    || body.contains("\"completed\"");

            record(id, "Spec Streaming", hasEvents,
                    "events=" + eventCount + ", completed=" + hasCompleted, ms);
        } catch (Exception e) {
            record(id, "Spec Streaming", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 10. error-task-not-found — GetTask with nonexistent ID returns error */
    static void testErrorTaskNotFound(String baseUrl) {
        String id = "jsonrpc/error-task-not-found";
        long start = System.nanoTime();
        try {
            String fakeTaskId = "00000000-0000-0000-0000-000000000000";
            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "GetTask",
                        "id": "%s",
                        "params": {
                            "id": "%s"
                        }
                    }
                    """.formatted(rpcId, fakeTaskId);

            HttpResponse<String> resp = httpPost(baseUrl + "/spec", jsonBody);
            long ms = elapsed(start);

            String body = resp.body();
            boolean hasError = hasJsonRpcError(body);
            String errCode = extractJsonString(body, "code");
            String errMsg = extractJsonString(body, "message");

            record(id, "Error Task Not Found", hasError,
                    hasError
                            ? "code=" + errCode + ", message=" + truncate(errMsg, 50)
                            : "expected error, got success: " + truncate(body, 80),
                    ms);
        } catch (Exception e) {
            record(id, "Error Task Not Found", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 11. spec-multi-turn — 3-step multi-turn conversation */
    static void testSpecMultiTurn(String baseUrl) {
        String id = "jsonrpc/spec-multi-turn";
        long start = System.nanoTime();
        try {
            // Step 1: Start conversation
            String body1 = sendMessage(baseUrl + "/spec", "multi-turn start conversation");
            if (body1 == null) {
                record(id, "Spec Multi-Turn", false, "Step 1: null response", elapsed(start));
                return;
            }
            if (hasJsonRpcError(body1)) {
                record(id, "Spec Multi-Turn", false,
                        "Step 1 error: " + extractJsonString(body1, "message"), elapsed(start));
                return;
            }
            boolean step1InputRequired = body1.contains("TASK_STATE_INPUT_REQUIRED")
                    || body1.contains("\"input_required\"");

            // Extract taskId from step 1
            String taskId = null;
            int taskIdx = body1.indexOf("\"task\"");
            if (taskIdx >= 0) {
                String taskPortion = body1.substring(taskIdx);
                taskId = extractJsonString(taskPortion, "id");
            }
            if (taskId == null) {
                record(id, "Spec Multi-Turn", false, "Step 1: no taskId found", elapsed(start));
                return;
            }

            // Step 2: Follow-up with taskId
            String msgId2 = UUID.randomUUID().toString();
            String rpcId2 = UUID.randomUUID().toString();
            String jsonBody2 = """
                    {
                        "jsonrpc": "2.0",
                        "method": "SendMessage",
                        "id": "%s",
                        "params": {
                            "message": {
                                "messageId": "%s",
                                "role": "ROLE_USER",
                                "parts": [{"text": "follow-up message"}],
                                "taskId": "%s"
                            }
                        }
                    }
                    """.formatted(rpcId2, msgId2, taskId);

            HttpResponse<String> resp2 = httpPost(baseUrl + "/spec", jsonBody2);
            String body2 = resp2.body();
            boolean step2InputRequired = body2.contains("TASK_STATE_INPUT_REQUIRED")
                    || body2.contains("\"input_required\"");

            // Step 3: Send "done" to complete
            String msgId3 = UUID.randomUUID().toString();
            String rpcId3 = UUID.randomUUID().toString();
            String jsonBody3 = """
                    {
                        "jsonrpc": "2.0",
                        "method": "SendMessage",
                        "id": "%s",
                        "params": {
                            "message": {
                                "messageId": "%s",
                                "role": "ROLE_USER",
                                "parts": [{"text": "done"}],
                                "taskId": "%s"
                            }
                        }
                    }
                    """.formatted(rpcId3, msgId3, taskId);

            HttpResponse<String> resp3 = httpPost(baseUrl + "/spec", jsonBody3);
            long ms = elapsed(start);
            String body3 = resp3.body();
            boolean step3Completed = body3.contains("TASK_STATE_COMPLETED")
                    || body3.contains("\"completed\"");

            boolean passed = step1InputRequired && step2InputRequired && step3Completed;
            record(id, "Spec Multi-Turn", passed,
                    "step1=INPUT_REQUIRED:" + step1InputRequired
                            + ", step2=INPUT_REQUIRED:" + step2InputRequired
                            + ", step3=COMPLETED:" + step3Completed
                            + ", taskId=" + truncate(taskId, 36), ms);
        } catch (Exception e) {
            record(id, "Spec Multi-Turn", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 12. spec-task-cancel — Cancel a task via streaming */
    static void testSpecTaskCancel(String baseUrl) {
        String id = "jsonrpc/spec-task-cancel";
        long start = System.nanoTime();
        try {
            // Start streaming to get taskId — use InputStream to read events as they arrive
            String msgId = UUID.randomUUID().toString();
            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "SendStreamingMessage",
                        "id": "%s",
                        "params": {
                            "message": {
                                "messageId": "%s",
                                "role": "ROLE_USER",
                                "parts": [{"text": "task-cancel"}]
                            }
                        }
                    }
                    """.formatted(rpcId, msgId);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(10))
                    .build();

            HttpResponse<java.io.InputStream> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofInputStream());

            if (resp.statusCode() != 200) {
                record(id, "Spec Task Cancel", false, "HTTP " + resp.statusCode(), elapsed(start));
                return;
            }

            // Read SSE events line by line, extract taskId from first event
            String taskId = null;
            try (var reader = new java.io.BufferedReader(new java.io.InputStreamReader(resp.body()))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.startsWith("data:")) continue;
                    String data = line.substring(5).trim();
                    int taskIdx = data.indexOf("\"task\"");
                    if (taskIdx >= 0) {
                        String taskPortion = data.substring(taskIdx);
                        taskId = extractJsonString(taskPortion, "id");
                    }
                    if (taskId == null) {
                        taskId = extractJsonString(data, "id");
                    }
                    if (taskId != null) break;
                }
            }

            if (taskId == null) {
                record(id, "Spec Task Cancel", false, "no taskId from streaming", elapsed(start));
                return;
            }

            // Send CancelTask
            String cancelRpcId = UUID.randomUUID().toString();
            String cancelBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "CancelTask",
                        "id": "%s",
                        "params": {
                            "id": "%s"
                        }
                    }
                    """.formatted(cancelRpcId, taskId);

            HttpResponse<String> cancelResp = httpPost(baseUrl + "/spec", cancelBody);
            long ms = elapsed(start);
            String cancelResult = cancelResp.body();

            boolean canceled = cancelResult.contains("TASK_STATE_CANCELED")
                    || cancelResult.contains("\"canceled\"");

            String state = extractTaskState(cancelResult);
            record(id, "Spec Task Cancel", canceled,
                    "taskId=" + truncate(taskId, 36) + ", state=" + state, ms);
        } catch (Exception e) {
            record(id, "Spec Task Cancel", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 13. spec-list-tasks — List tasks */
    static void testSpecListTasks(String baseUrl) {
        String id = "jsonrpc/spec-list-tasks";
        long start = System.nanoTime();
        try {
            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "ListTasks",
                        "id": "%s",
                        "params": {}
                    }
                    """.formatted(rpcId);

            HttpResponse<String> resp = httpPost(baseUrl + "/spec", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "Spec List Tasks", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();
            if (hasJsonRpcError(body)) {
                record(id, "Spec List Tasks", false,
                        "JSON-RPC error: " + extractJsonString(body, "message"), ms);
                return;
            }

            boolean hasResult = body.contains("\"result\"");
            int taskCount = countOccurrences(body, "\"state\"");
            boolean hasAtLeastOne = taskCount >= 1;

            record(id, "Spec List Tasks", hasResult && hasAtLeastOne,
                    "hasResult=" + hasResult + ", taskCount>=" + taskCount, ms);
        } catch (Exception e) {
            record(id, "Spec List Tasks", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** 14. spec-return-immediately — returnImmediately flag (expected to fail) */
    static void testSpecReturnImmediately(String baseUrl) {
        String id = "jsonrpc/spec-return-immediately";
        long start = System.nanoTime();
        try {
            String msgId = UUID.randomUUID().toString();
            String rpcId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "jsonrpc": "2.0",
                        "method": "SendMessage",
                        "id": "%s",
                        "params": {
                            "message": {
                                "messageId": "%s",
                                "role": "ROLE_USER",
                                "parts": [{"text": "long-running test"}]
                            },
                            "configuration": {
                                "returnImmediately": true
                            }
                        }
                    }
                    """.formatted(rpcId, msgId);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(15))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            long ms = elapsed(start);

            String body = resp.body();
            String state = extractTaskState(body);
            boolean isTerminal = state != null
                    && (state.contains("COMPLETED") || state.contains("completed"));
            boolean fastEnough = ms < 2000;
            boolean tooSlow = ms > 3000;

            // Pass if <2s with non-terminal state. FAIL if >3s or COMPLETED.
            boolean passed = fastEnough && !isTerminal;

            String detail;
            if (tooSlow) {
                detail = "returnImmediately ignored by SDK, took " + ms + "ms";
            } else if (isTerminal) {
                detail = "returnImmediately ignored by SDK, state=" + state;
            } else {
                detail = "state=" + state + ", time=" + ms + "ms";
            }

            record(id, "Spec Return Immediately", passed, detail, ms);
        } catch (Exception e) {
            record(id, "Spec Return Immediately", false, exceptionDetail(e), elapsed(start));
        }
    }

    // ─────────────────── REST binding test implementations ───────────────────

    /** REST helper: build a bare JSON message body (no JSON-RPC wrapper). */
    static String makeRestMessageBody(String text) {
        String msgId = UUID.randomUUID().toString();
        return """
                {
                    "message": {
                        "messageId": "%s",
                        "role": "ROLE_USER",
                        "parts": [{"text": "%s"}]
                    }
                }
                """.formatted(msgId, text);
    }

    /** REST 1. rest/agent-card-echo — Resolve echo agent card via REST endpoint */
    static void testRestAgentCardEcho(String baseUrl) {
        String id = "rest/agent-card-echo";
        long start = System.nanoTime();
        try {
            String url = baseUrl + "/echo/v1/card";
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Echo Agent Card", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            String name = extractJsonString(body, "name");
            boolean hasSkills = body.contains("\"skills\"");

            if (name != null && hasSkills) {
                int skillCount = countOccurrences(body, "\"id\"");
                record(id, "REST Echo Agent Card", true,
                        "name=" + name + ", skills=" + skillCount, ms);
            } else {
                record(id, "REST Echo Agent Card", false, "Missing name or skills", ms);
            }
        } catch (Exception e) {
            record(id, "REST Echo Agent Card", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 2. rest/agent-card-spec — Resolve spec agent card via REST endpoint */
    static void testRestAgentCardSpec(String baseUrl) {
        String id = "rest/agent-card-spec";
        long start = System.nanoTime();
        try {
            String url = baseUrl + "/spec/v1/card";
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Agent Card", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            String name = extractJsonString(body, "name");
            boolean hasSkills = body.contains("\"skills\"");

            if (name != null && hasSkills) {
                int skillCount = countOccurrences(body, "\"id\"");
                record(id, "REST Spec Agent Card", true,
                        "name=" + name + ", skills=" + skillCount, ms);
            } else {
                record(id, "REST Spec Agent Card", false, "Missing name or skills", ms);
            }
        } catch (Exception e) {
            record(id, "REST Spec Agent Card", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 3. rest/echo-send-message — Send message to echo agent via REST */
    static void testRestEchoSendMessage(String baseUrl) {
        String id = "rest/echo-send-message";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("hello from Java REST");
            HttpResponse<String> resp = httpPost(baseUrl + "/echo/v1/message:send", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Echo Send Message", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            String text = extractResponseText(body);
            boolean echoed = text != null && text.toLowerCase().contains("hello from java rest");
            record(id, "REST Echo Send Message", echoed,
                    echoed ? "echo=" + truncate(text, 80) : "unexpected: " + truncate(text, 80), ms);
        } catch (Exception e) {
            record(id, "REST Echo Send Message", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 4. rest/spec-message-only — Message-only skill via REST */
    static void testRestSpecMessageOnly(String baseUrl) {
        String id = "rest/spec-message-only";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("message-only hello from Java REST");
            HttpResponse<String> resp = httpPost(baseUrl + "/spec/v1/message:send", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Message Only", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            boolean hasMessage = body.contains("\"message\"");
            String text = extractResponseText(body);
            boolean hasText = text != null && !text.isEmpty();
            boolean isMessageOnly = !body.contains("\"TASK_STATE_");

            record(id, "REST Spec Message Only", hasMessage && hasText,
                    "text=" + truncate(text, 60) + ", messageOnly=" + isMessageOnly, ms);
        } catch (Exception e) {
            record(id, "REST Spec Message Only", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 5. rest/spec-task-lifecycle — Task lifecycle via REST, capture task ID */
    static void testRestSpecTaskLifecycle(String baseUrl) {
        String id = "rest/spec-task-lifecycle";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("task-lifecycle process this");
            HttpResponse<String> resp = httpPost(baseUrl + "/spec/v1/message:send", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Task Lifecycle", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            boolean completed = body.contains("TASK_STATE_COMPLETED")
                    || body.contains("\"completed\"");
            boolean hasArtifacts = body.contains("\"artifacts\"");

            // Capture taskId for rest/spec-get-task
            int taskIdx = body.indexOf("\"task\"");
            if (taskIdx >= 0) {
                String taskPortion = body.substring(taskIdx);
                capturedRestTaskId = extractJsonString(taskPortion, "id");
            }
            if (capturedRestTaskId == null) {
                capturedRestTaskId = "UNKNOWN";
            }

            String text = extractResponseText(body);
            record(id, "REST Spec Task Lifecycle", completed && hasArtifacts,
                    "completed=" + completed + ", artifacts=" + hasArtifacts
                            + ", taskId=" + truncate(capturedRestTaskId, 36)
                            + ", text=" + truncate(text, 40), ms);
        } catch (Exception e) {
            record(id, "REST Spec Task Lifecycle", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 6. rest/spec-get-task — GetTask via REST GET endpoint */
    static void testRestSpecGetTask(String baseUrl) {
        String id = "rest/spec-get-task";
        long start = System.nanoTime();
        try {
            if (capturedRestTaskId == null) {
                record(id, "REST Spec Get Task", false, "no taskId from REST lifecycle test", elapsed(start));
                return;
            }

            String url = baseUrl + "/spec/v1/tasks/" + capturedRestTaskId;
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Get Task", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();
            boolean hasTaskId = body.contains(capturedRestTaskId);
            String state = extractJsonString(body, "state");
            if (state == null) {
                state = extractTaskState(body);
            }

            record(id, "REST Spec Get Task", hasTaskId,
                    "found=" + hasTaskId + ", state=" + state, ms);
        } catch (Exception e) {
            record(id, "REST Spec Get Task", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 7. rest/spec-task-failure — Task failure via REST */
    static void testRestSpecTaskFailure(String baseUrl) {
        String id = "rest/spec-task-failure";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("task-failure trigger error");
            HttpResponse<String> resp = httpPost(baseUrl + "/spec/v1/message:send", jsonBody);
            long ms = elapsed(start);

            String body = resp.body();
            boolean failed = body.contains("TASK_STATE_FAILED")
                    || body.contains("\"failed\"");

            // A non-200 status with error info is also acceptable
            if (!failed && resp.statusCode() != 200) {
                String errMsg = extractJsonString(body, "message");
                if (errMsg == null) errMsg = "HTTP " + resp.statusCode();
                failed = true;
                record(id, "REST Spec Task Failure", failed,
                        "error=" + truncate(errMsg, 60), ms);
                return;
            }

            String state = extractTaskState(body);
            record(id, "REST Spec Task Failure", failed,
                    "state=" + state + ", hasFailed=" + failed, ms);
        } catch (Exception e) {
            record(id, "REST Spec Task Failure", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 8. rest/spec-data-types — Data types via REST */
    static void testRestSpecDataTypes(String baseUrl) {
        String id = "rest/spec-data-types";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("data-types show all");
            HttpResponse<String> resp = httpPost(baseUrl + "/spec/v1/message:send", jsonBody);
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Data Types", false, "HTTP " + resp.statusCode(), ms);
                return;
            }
            String body = resp.body();
            boolean hasText = body.contains("\"text\"");
            boolean hasData = body.contains("\"data\"");
            boolean hasFile = body.contains("\"mediaType\"") || body.contains("\"url\"");

            String detail = "text=" + hasText + ", data=" + hasData + ", file=" + hasFile;
            boolean pass = hasText && (hasData || hasFile);
            record(id, "REST Spec Data Types", pass, detail, ms);
        } catch (Exception e) {
            record(id, "REST Spec Data Types", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 9. rest/spec-streaming — SSE streaming via REST endpoint */
    static void testRestSpecStreaming(String baseUrl) {
        String id = "rest/spec-streaming";
        long start = System.nanoTime();
        try {
            String jsonBody = makeRestMessageBody("streaming generate output");

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec/v1/message:stream"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(30))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Streaming", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();

            // Count SSE data: lines
            int eventCount = 0;
            for (String line : body.split("\n")) {
                if (line.startsWith("data:")) {
                    eventCount++;
                }
            }

            boolean hasEvents = eventCount > 0;
            boolean hasCompleted = body.contains("TASK_STATE_COMPLETED")
                    || body.contains("\"completed\"");

            record(id, "REST Spec Streaming", hasEvents,
                    "events=" + eventCount + ", completed=" + hasCompleted, ms);
        } catch (Exception e) {
            record(id, "REST Spec Streaming", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 10. rest/error-task-not-found — GET nonexistent task returns HTTP 404 */
    static void testRestErrorTaskNotFound(String baseUrl) {
        String id = "rest/error-task-not-found";
        long start = System.nanoTime();
        try {
            String fakeTaskId = "00000000-0000-0000-0000-000000000000";
            String url = baseUrl + "/spec/v1/tasks/" + fakeTaskId;
            HttpResponse<String> resp = httpGet(url);
            long ms = elapsed(start);

            int status = resp.statusCode();
            boolean is404 = status == 404;
            String body = resp.body();
            String errMsg = extractJsonString(body, "message");

            record(id, "REST Error Task Not Found", is404,
                    is404
                            ? "HTTP 404" + (errMsg != null ? ", message=" + truncate(errMsg, 50) : "")
                            : "expected HTTP 404, got " + status + ": " + truncate(body, 80),
                    ms);
        } catch (Exception e) {
            record(id, "REST Error Task Not Found", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 11. rest/spec-multi-turn — 3-step multi-turn conversation via REST */
    static void testRestSpecMultiTurn(String baseUrl) {
        String id = "rest/spec-multi-turn";
        long start = System.nanoTime();
        try {
            // Step 1: Start conversation
            String jsonBody1 = makeRestMessageBody("multi-turn start conversation");
            HttpResponse<String> resp1 = httpPost(baseUrl + "/spec/v1/message:send", jsonBody1);

            if (resp1.statusCode() != 200) {
                record(id, "REST Spec Multi-Turn", false,
                        "Step 1: HTTP " + resp1.statusCode(), elapsed(start));
                return;
            }
            String body1 = resp1.body();
            boolean step1InputRequired = body1.contains("TASK_STATE_INPUT_REQUIRED")
                    || body1.contains("\"input_required\"");

            // Extract taskId
            String taskId = null;
            int taskIdx = body1.indexOf("\"task\"");
            if (taskIdx >= 0) {
                String taskPortion = body1.substring(taskIdx);
                taskId = extractJsonString(taskPortion, "id");
            }
            if (taskId == null) {
                record(id, "REST Spec Multi-Turn", false,
                        "Step 1: no taskId found", elapsed(start));
                return;
            }

            // Step 2: Follow-up with taskId
            String msgId2 = UUID.randomUUID().toString();
            String jsonBody2 = """
                    {
                        "message": {
                            "messageId": "%s",
                            "role": "ROLE_USER",
                            "parts": [{"text": "follow-up message"}],
                            "taskId": "%s"
                        }
                    }
                    """.formatted(msgId2, taskId);
            HttpResponse<String> resp2 = httpPost(baseUrl + "/spec/v1/message:send", jsonBody2);
            String body2 = resp2.body();
            boolean step2InputRequired = body2.contains("TASK_STATE_INPUT_REQUIRED")
                    || body2.contains("\"input_required\"");

            // Step 3: Send "done" to complete
            String msgId3 = UUID.randomUUID().toString();
            String jsonBody3 = """
                    {
                        "message": {
                            "messageId": "%s",
                            "role": "ROLE_USER",
                            "parts": [{"text": "done"}],
                            "taskId": "%s"
                        }
                    }
                    """.formatted(msgId3, taskId);
            HttpResponse<String> resp3 = httpPost(baseUrl + "/spec/v1/message:send", jsonBody3);
            long ms = elapsed(start);
            String body3 = resp3.body();
            boolean step3Completed = body3.contains("TASK_STATE_COMPLETED")
                    || body3.contains("\"completed\"");

            boolean passed = step1InputRequired && step2InputRequired && step3Completed;
            record(id, "REST Spec Multi-Turn", passed,
                    "step1=INPUT_REQUIRED:" + step1InputRequired
                            + ", step2=INPUT_REQUIRED:" + step2InputRequired
                            + ", step3=COMPLETED:" + step3Completed
                            + ", taskId=" + truncate(taskId, 36), ms);
        } catch (Exception e) {
            record(id, "REST Spec Multi-Turn", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 12. rest/spec-task-cancel — Cancel a task via REST streaming */
    static void testRestSpecTaskCancel(String baseUrl) {
        String id = "rest/spec-task-cancel";
        long start = System.nanoTime();
        try {
            // Start streaming to get taskId — use InputStream to read events as they arrive
            String jsonBody = makeRestMessageBody("task-cancel");

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec/v1/message:stream"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(10))
                    .build();

            HttpResponse<java.io.InputStream> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofInputStream());

            if (resp.statusCode() != 200) {
                record(id, "REST Spec Task Cancel", false,
                        "HTTP " + resp.statusCode(), elapsed(start));
                return;
            }

            // Read SSE events line by line, extract taskId from first event
            String taskId = null;
            try (var reader = new java.io.BufferedReader(new java.io.InputStreamReader(resp.body()))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.startsWith("data:")) continue;
                    String data = line.substring(5).trim();
                    int taskIdx = data.indexOf("\"task\"");
                    if (taskIdx >= 0) {
                        String taskPortion = data.substring(taskIdx);
                        taskId = extractJsonString(taskPortion, "id");
                    }
                    if (taskId == null) {
                        // Also check statusUpdate.taskId
                        int suIdx = data.indexOf("\"taskId\"");
                        if (suIdx >= 0) {
                            taskId = extractJsonString(data.substring(suIdx - 1), "taskId");
                        }
                    }
                    if (taskId != null) break;
                }
            }

            if (taskId == null) {
                record(id, "REST Spec Task Cancel", false,
                        "no taskId from streaming", elapsed(start));
                return;
            }

            // Send cancel via REST: POST /v1/tasks/{id}:cancel
            String cancelUrl = baseUrl + "/spec/v1/tasks/" + taskId + ":cancel";
            HttpRequest cancelReq = HttpRequest.newBuilder()
                    .uri(URI.create(cancelUrl))
                    .POST(HttpRequest.BodyPublishers.ofString("{}"))
                    .header("Content-Type", "application/json")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(10))
                    .build();

            HttpResponse<String> cancelResp = httpClient.send(cancelReq,
                    HttpResponse.BodyHandlers.ofString());
            long ms = elapsed(start);
            String cancelResult = cancelResp.body();

            boolean canceled = cancelResult.contains("TASK_STATE_CANCELED")
                    || cancelResult.contains("\"canceled\"");

            String state = extractTaskState(cancelResult);
            record(id, "REST Spec Task Cancel", canceled,
                    "taskId=" + truncate(taskId, 36) + ", state=" + state, ms);
        } catch (Exception e) {
            record(id, "REST Spec Task Cancel", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 13. rest/spec-list-tasks — List tasks via REST */
    static void testRestSpecListTasks(String baseUrl) {
        String id = "rest/spec-list-tasks";
        long start = System.nanoTime();
        try {
            HttpResponse<String> resp = httpGet(baseUrl + "/spec/v1/tasks");
            long ms = elapsed(start);

            if (resp.statusCode() != 200) {
                record(id, "REST Spec List Tasks", false, "HTTP " + resp.statusCode(), ms);
                return;
            }

            String body = resp.body();
            boolean isArray = body.trim().startsWith("[");
            int taskCount = countOccurrences(body, "\"state\"");
            boolean hasAtLeastOne = taskCount >= 1;

            record(id, "REST Spec List Tasks", hasAtLeastOne,
                    "isArray=" + isArray + ", taskCount>=" + taskCount, ms);
        } catch (Exception e) {
            record(id, "REST Spec List Tasks", false, exceptionDetail(e), elapsed(start));
        }
    }

    /** REST 14. rest/spec-return-immediately — returnImmediately flag via REST (expected to fail) */
    static void testRestSpecReturnImmediately(String baseUrl) {
        String id = "rest/spec-return-immediately";
        long start = System.nanoTime();
        try {
            String msgId = UUID.randomUUID().toString();
            String jsonBody = """
                    {
                        "message": {
                            "messageId": "%s",
                            "role": "ROLE_USER",
                            "parts": [{"text": "long-running test"}]
                        },
                        "configuration": {
                            "returnImmediately": true
                        }
                    }
                    """.formatted(msgId);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/spec/v1/message:send"))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .header("A2A-Version", A2A_VERSION)
                    .timeout(Duration.ofSeconds(15))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            long ms = elapsed(start);

            String body = resp.body();
            String state = extractTaskState(body);
            boolean isTerminal = state != null
                    && (state.contains("COMPLETED") || state.contains("completed"));
            boolean fastEnough = ms < 2000;
            boolean tooSlow = ms > 3000;

            // Pass if <2s with non-terminal state. FAIL if >3s or COMPLETED.
            boolean passed = fastEnough && !isTerminal;

            String detail;
            if (tooSlow) {
                detail = "returnImmediately ignored by SDK, took " + ms + "ms";
            } else if (isTerminal) {
                detail = "returnImmediately ignored by SDK, state=" + state;
            } else {
                detail = "state=" + state + ", time=" + ms + "ms";
            }

            record(id, "REST Spec Return Immediately", passed, detail, ms);
        } catch (Exception e) {
            record(id, "REST Spec Return Immediately", false, exceptionDetail(e), elapsed(start));
        }
    }

    // ─────────────────────── HTTP helpers ───────────────────────

    /** Send a JSON-RPC SendMessage request and return the response body. */
    static String sendMessage(String url, String text) throws IOException, InterruptedException {
        String msgId = UUID.randomUUID().toString();
        String rpcId = UUID.randomUUID().toString();
        String jsonBody = """
                {
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "id": "%s",
                    "params": {
                        "message": {
                            "messageId": "%s",
                            "role": "ROLE_USER",
                            "parts": [{"text": "%s"}]
                        }
                    }
                }
                """.formatted(rpcId, msgId, text);

        HttpResponse<String> resp = httpPost(url, jsonBody);
        if (resp.statusCode() != 200) {
            return null;
        }
        return resp.body();
    }

    /** HTTP GET with A2A-Version header. */
    static HttpResponse<String> httpGet(String url) throws IOException, InterruptedException {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .GET()
                .header("A2A-Version", A2A_VERSION)
                .timeout(Duration.ofSeconds(15))
                .build();
        return httpClient.send(req, HttpResponse.BodyHandlers.ofString());
    }

    /** HTTP POST with JSON content type and A2A-Version header. */
    static HttpResponse<String> httpPost(String url, String jsonBody)
            throws IOException, InterruptedException {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .header("Content-Type", "application/json")
                .header("A2A-Version", A2A_VERSION)
                .timeout(Duration.ofSeconds(30))
                .build();
        return httpClient.send(req, HttpResponse.BodyHandlers.ofString());
    }

    // ─────────────────────── JSON helpers ───────────────────────

    /** Check whether the JSON-RPC response contains an "error" object (and no "result"). */
    static boolean hasJsonRpcError(String json) {
        // Match top-level "error" that is an object, not nested inside "result"
        int errIdx = json.indexOf("\"error\"");
        if (errIdx < 0) return false;
        int resultIdx = json.indexOf("\"result\"");
        // If "error" appears before any "result", it's a top-level error
        return resultIdx < 0 || errIdx < resultIdx;
    }

    /** Simple extraction of a JSON string value for a given key. */
    static String extractJsonString(String json, String key) {
        String pattern = "\"" + key + "\"";
        int idx = json.indexOf(pattern);
        if (idx < 0) return null;
        int colonIdx = json.indexOf(':', idx + pattern.length());
        if (colonIdx < 0) return null;
        // Skip whitespace after colon
        int pos = colonIdx + 1;
        while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) pos++;
        if (pos >= json.length()) return null;

        char ch = json.charAt(pos);
        if (ch == '"') {
            // String value
            int quoteEnd = pos + 1;
            while (quoteEnd < json.length()) {
                quoteEnd = json.indexOf('"', quoteEnd);
                if (quoteEnd < 0) return null;
                // Check for escape
                int backslashes = 0;
                int scan = quoteEnd - 1;
                while (scan >= 0 && json.charAt(scan) == '\\') { backslashes++; scan--; }
                if (backslashes % 2 == 0) break; // unescaped quote
                quoteEnd++;
            }
            return json.substring(pos + 1, quoteEnd);
        } else if (ch == '-' || Character.isDigit(ch)) {
            // Number value — return as string
            int end = pos;
            while (end < json.length() && !Character.isWhitespace(json.charAt(end))
                    && json.charAt(end) != ',' && json.charAt(end) != '}' && json.charAt(end) != ']') {
                end++;
            }
            return json.substring(pos, end);
        }
        return null;
    }

    /** Extract the first text part from a response (looks inside parts array). */
    static String extractResponseText(String json) {
        int partsIdx = json.indexOf("\"parts\"");
        if (partsIdx >= 0) {
            return extractJsonString(json.substring(partsIdx), "text");
        }
        return extractJsonString(json, "text");
    }

    /** Try to find task state in the response body. */
    static String extractTaskState(String body) {
        // Look for TASK_STATE_* enum values
        for (String state : List.of("TASK_STATE_COMPLETED", "TASK_STATE_FAILED",
                "TASK_STATE_WORKING", "TASK_STATE_INPUT_REQUIRED",
                "TASK_STATE_CANCELED", "TASK_STATE_UNKNOWN")) {
            if (body.contains(state)) return state;
        }
        // Also check for simple string states (completed, failed, etc.)
        String stateVal = extractJsonString(body, "state");
        return stateVal;
    }

    // ─────────────────────── Utility ───────────────────────

    static long elapsed(long startNanos) {
        return (System.nanoTime() - startNanos) / 1_000_000;
    }

    static String truncate(String s, int max) {
        if (s == null) return "<null>";
        s = s.replace("\n", " ").replace("\r", "");
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }

    static int countOccurrences(String haystack, String needle) {
        int count = 0;
        int idx = 0;
        while ((idx = haystack.indexOf(needle, idx)) >= 0) {
            count++;
            idx += needle.length();
        }
        return count;
    }

    static String exceptionDetail(Exception e) {
        return e.getClass().getSimpleName() + ": " + e.getMessage();
    }

    static String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    // ─────────────────────── Recording & Output ───────────────────────

    static void record(String id, String name, boolean passed, String detail, long durationMs) {
        results.add(new TestResult(id, name, passed, detail, durationMs));
        String tag = passed ? "[PASS]" : "[FAIL]";
        System.out.printf("  %s %s — %s%n", tag, id, detail);
    }

    static void writeResultsJson(String baseUrl) {
        String timestamp = Instant.now().atOffset(ZoneOffset.UTC)
                .format(DateTimeFormatter.ISO_INSTANT);

        var sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"client\": \"java\",\n");
        sb.append("  \"sdk\": \"java.net.http (raw)\",\n");
        sb.append("  \"protocolVersion\": \"").append(A2A_VERSION).append("\",\n");
        sb.append("  \"timestamp\": \"").append(timestamp).append("\",\n");
        sb.append("  \"baseUrl\": \"").append(escapeJson(baseUrl)).append("\",\n");
        sb.append("  \"results\": [\n");

        for (int i = 0; i < results.size(); i++) {
            TestResult r = results.get(i);
            sb.append("    {");
            sb.append("\"id\": \"").append(escapeJson(r.id)).append("\", ");
            sb.append("\"name\": \"").append(escapeJson(r.name)).append("\", ");
            sb.append("\"passed\": ").append(r.passed).append(", ");
            sb.append("\"detail\": \"").append(escapeJson(r.detail)).append("\", ");
            sb.append("\"durationMs\": ").append(r.durationMs);
            sb.append("}");
            if (i < results.size() - 1) sb.append(",");
            sb.append("\n");
        }

        sb.append("  ]\n");
        sb.append("}\n");

        try {
            // Write next to the source file (current working directory)
            Path outPath = Path.of("results.json");
            Files.writeString(outPath, sb.toString());
            System.out.println("\nResults written to: " + outPath.toAbsolutePath());
        } catch (IOException e) {
            System.err.println("Failed to write results.json: " + e.getMessage());
        }
    }
}
