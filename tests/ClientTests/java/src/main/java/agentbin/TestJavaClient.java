package agentbin;

import org.a2aproject.sdk.A2A;
import org.a2aproject.sdk.client.Client;
import org.a2aproject.sdk.client.ClientBuilder;
import org.a2aproject.sdk.client.ClientEvent;
import org.a2aproject.sdk.client.MessageEvent;
import org.a2aproject.sdk.client.TaskEvent;
import org.a2aproject.sdk.client.TaskUpdateEvent;
import org.a2aproject.sdk.client.transport.jsonrpc.JSONRPCTransport;
import org.a2aproject.sdk.client.transport.jsonrpc.JSONRPCTransportConfigBuilder;
import org.a2aproject.sdk.client.transport.rest.RestTransport;
import org.a2aproject.sdk.client.transport.rest.RestTransportConfigBuilder;
import org.a2aproject.sdk.client.transport.spi.interceptors.ClientCallInterceptor;
import org.a2aproject.sdk.client.transport.spi.interceptors.ClientCallContext;
import org.a2aproject.sdk.client.transport.spi.interceptors.PayloadAndHeaders;
import org.a2aproject.sdk.spec.*;

import java.io.*;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import java.util.regex.*;

/**
 * AgentBin Java SDK acceptance tests.
 * Tests both JSON-RPC and HTTP+JSON REST bindings using the official A2A Java SDK.
 */
public class TestJavaClient {

    static final String DEFAULT_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";
    static final Map<String, String> VERSION_HEADERS = Map.of("A2A-Version", "1.0");
    static final List<TestResult> results = new ArrayList<>();

    record TestResult(String id, String name, boolean passed, String detail, long durationMs) {}

    static void record(String id, String name, boolean passed, String detail, long ms) {
        results.add(new TestResult(id, name, passed, detail, ms));
        System.out.printf("  [%s] %s — %s%n", passed ? "PASS" : "FAIL", id, detail);
    }

    // Interceptor to inject A2A-Version header on every SDK call
    static class VersionInterceptor extends ClientCallInterceptor {
        @Override
        public PayloadAndHeaders intercept(String method, Object payload,
                Map<String, String> headers, AgentCard card, ClientCallContext ctx) {
            var newHeaders = new HashMap<>(headers);
            newHeaders.put("A2A-Version", "1.0");
            return new PayloadAndHeaders(payload, newHeaders);
        }
    }

    // Functional interface to apply transport config to a ClientBuilder
    @FunctionalInterface
    interface TransportConfigurer {
        ClientBuilder apply(ClientBuilder builder);
    }

    public static void main(String[] args) throws Exception {
        String baseUrl = args.length > 0 ? args[0].replaceAll("/$", "") : DEFAULT_URL;
        System.out.println("AgentBin Java SDK Tests — " + baseUrl + "\n");

        var interceptor = new VersionInterceptor();

        TransportConfigurer jsonrpc = b ->
                b.withTransport(JSONRPCTransport.class,
                        new JSONRPCTransportConfigBuilder().addInterceptor(interceptor));

        TransportConfigurer rest = b ->
                b.withTransport(RestTransport.class,
                        new RestTransportConfigBuilder().addInterceptor(interceptor));

        System.out.println("── JSON-RPC Binding (SDK) ──");
        runBindingTests(baseUrl, "jsonrpc", jsonrpc);

        System.out.println("\n── HTTP+JSON REST Binding (SDK) ──");
        runBindingTests(baseUrl, "rest", rest);

        System.out.println("\n── v0.3 Backward Compatibility ──");
        runV03Tests(baseUrl);

        int passed = (int) results.stream().filter(r -> r.passed).count();
        int failed = results.size() - passed;
        System.out.println("\n══════════════════════════════════════════");
        System.out.printf("  %d passed, %d failed, %d total%n", passed, failed, results.size());
        System.out.println("══════════════════════════════════════════");
        if (failed > 0) {
            System.out.println("\nFailed tests:");
            results.stream().filter(r -> !r.passed)
                    .forEach(r -> System.out.printf("  ✗ %s — %s%n", r.id, r.detail));
        }

        writeResultsJson(baseUrl);
        System.exit(failed > 0 ? 1 : 0);
    }

    static void runBindingTests(String baseUrl, String binding, TransportConfigurer tc) {
        String echoUrl = baseUrl + "/echo";
        String specUrl = baseUrl + "/spec";

        testAgentCard(binding + "/agent-card-echo", "Echo Agent Card", echoUrl);
        testAgentCard(binding + "/agent-card-spec", "Spec Agent Card", specUrl);
        testSpecExtendedCard(binding + "/spec-extended-card", specUrl, binding);
        testEchoSendMessage(binding + "/echo-send-message", echoUrl, tc);
        testSpecMessageOnly(binding + "/spec-message-only", specUrl, tc);
        testSpecTaskLifecycle(binding + "/spec-task-lifecycle", binding + "/spec-get-task", specUrl, tc);
        testSpecTaskFailure(binding + "/spec-task-failure", specUrl, tc);
        testSpecDataTypes(binding + "/spec-data-types", specUrl, tc);
        testSpecStreaming(binding + "/spec-streaming", specUrl, tc);
        testSpecMultiTurn(binding + "/spec-multi-turn", specUrl, tc);
        testSpecTaskCancel(binding + "/spec-task-cancel", specUrl, tc);
        testSpecCancelWithMetadata(binding + "/spec-cancel-with-metadata", specUrl, tc);
        testSpecListTasks(binding + "/spec-list-tasks", specUrl, tc);
        testSpecReturnImmediately(binding + "/spec-return-immediately", specUrl, tc);
        testErrorTaskNotFound(binding + "/error-task-not-found", specUrl, tc);
        testErrorCancelNotFound(binding + "/error-cancel-not-found", specUrl, tc);
        testErrorCancelTerminal(binding + "/error-cancel-terminal", specUrl, tc);
        testErrorSendTerminal(binding + "/error-send-terminal", specUrl, tc);
        testErrorSendInvalidTask(binding + "/error-send-invalid-task", specUrl, tc);
        testErrorPushNotSupported(binding + "/error-push-not-supported", specUrl, tc);
        testSubscribeToTask(binding + "/subscribe-to-task", specUrl, tc);
        testErrorSubscribeNotFound(binding + "/error-subscribe-not-found", specUrl, tc);
        testStreamMessageOnly(binding + "/stream-message-only", specUrl, tc);
        testStreamTaskLifecycle(binding + "/stream-task-lifecycle", specUrl, tc);
        testMultiTurnContextPreserved(binding + "/multi-turn-context-preserved", specUrl, tc);
        testGetTaskWithHistory(binding + "/get-task-with-history", specUrl, tc);
        testGetTaskAfterFailure(binding + "/get-task-after-failure", specUrl, tc);
    }

    // Build an AgentCard manually when SDK card fetch fails (e.g., protobuf can't parse .NET output)
    static AgentCard buildCardManually(String agentUrl, boolean streaming) {
        return AgentCard.builder()
                .name("Manual Card")
                .description("Manually constructed — SDK card fetch failed")
                .version("1.0.0")
                .supportedInterfaces(List.of(
                        new AgentInterface("JSONRPC", agentUrl, "", "1.0"),
                        new AgentInterface("HTTP+JSON", agentUrl + "/v1", "", "1.0")))
                .capabilities(new AgentCapabilities(streaming, false, false, List.of()))
                .defaultInputModes(List.of("text/plain"))
                .defaultOutputModes(List.of("text/plain"))
                .skills(List.of())
                .build();
    }

    // Try SDK card fetch, fallback to manual construction
    static AgentCard getCard(String agentUrl, boolean streaming) {
        try {
            return A2A.getAgentCard(agentUrl, null, VERSION_HEADERS);
        } catch (Exception e) {
            System.out.println("    ⚠ SDK card fetch failed, using manual card: " + e.getMessage());
            return buildCardManually(agentUrl, streaming);
        }
    }

    // ── Test implementations ──────────────────────────────────────────

    static void testAgentCard(String id, String name, String agentUrl) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = A2A.getAgentCard(agentUrl, null, VERSION_HEADERS);
            boolean ok = card.name() != null && !card.name().isEmpty();
            record(id, name, ok,
                    "name=" + card.name() + ", skills=" + card.skills().size(),
                    System.currentTimeMillis() - start);
        } catch (Exception e) {
            record(id, name, false, e.getMessage(), System.currentTimeMillis() - start);
        }
    }

    static void testSpecExtendedCard(String id, String agentUrl, String binding) {
        long start = System.currentTimeMillis();
        try {
            // Step 1: Get public card and verify extendedAgentCard capability
            AgentCard publicCard = A2A.getAgentCard(agentUrl, null, VERSION_HEADERS);
            if (publicCard.capabilities() == null || !publicCard.capabilities().extendedAgentCard()) {
                record(id, "Extended Agent Card", false,
                        "extendedAgentCard capability not true",
                        System.currentTimeMillis() - start);
                return;
            }

            int publicSkillCount = publicCard.skills() != null ? publicCard.skills().size() : 0;

            // Step 2: Call GetExtendedAgentCard with auth header
            HttpClient httpClient = HttpClient.newHttpClient();
            HttpRequest request = null;
            
            if (binding.equals("rest")) {
                // REST: GET /spec/extendedAgentCard with Authorization header
                request = HttpRequest.newBuilder()
                        .uri(URI.create(agentUrl + "/extendedAgentCard"))
                        .header("A2A-Version", "1.0")
                        .header("Authorization", "Bearer agentbin-test-token")
                        .GET()
                        .build();
            } else {
                // JSON-RPC: POST to /spec with GetExtendedAgentCard method
                String requestBody = "{\"jsonrpc\":\"2.0\",\"method\":\"GetExtendedAgentCard\",\"id\":\"ext-card-1\",\"params\":{}}";
                request = HttpRequest.newBuilder()
                        .uri(URI.create(agentUrl))
                        .header("Content-Type", "application/json")
                        .header("A2A-Version", "1.0")
                        .header("Authorization", "Bearer agentbin-test-token")
                        .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                        .build();
            }

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                record(id, "Extended Agent Card", false,
                        "HTTP " + response.statusCode() + " from GetExtendedAgentCard",
                        System.currentTimeMillis() - start);
                return;
            }

            // Parse response
            String json = response.body();
            String cardJson = json;
            
            if (binding.equals("jsonrpc")) {
                // Extract result from JSON-RPC response
                if (!json.contains("\"result\"")) {
                    record(id, "Extended Agent Card", false,
                            "JSON-RPC response missing result field",
                            System.currentTimeMillis() - start);
                    return;
                }

                int resultStart = json.indexOf("\"result\"") + 9;
                resultStart = json.indexOf("{", resultStart);
                int depth = 0;
                int resultEnd = resultStart;
                for (int i = resultStart; i < json.length(); i++) {
                    char c = json.charAt(i);
                    if (c == '{') depth++;
                    if (c == '}') {
                        depth--;
                        if (depth == 0) {
                            resultEnd = i + 1;
                            break;
                        }
                    }
                }
                cardJson = json.substring(resultStart, resultEnd);
            }

            // Validate card JSON
            if (!cardJson.contains("\"name\"") || !cardJson.contains("\"skills\"")) {
                record(id, "Extended Agent Card", false,
                        "Extended card JSON missing name or skills",
                        System.currentTimeMillis() - start);
                return;
            }

            // Count skills and check for admin-status
            int extendedSkillCount = countJsonArrayItems(cardJson, "\"skills\"");
            boolean hasAdminStatus = cardJson.contains("\"admin-status\"");
            boolean hasMoreSkills = extendedSkillCount > publicSkillCount || hasAdminStatus;

            record(id, "Extended Agent Card", hasMoreSkills,
                    "publicSkills=" + publicSkillCount + ", extendedSkills=" + extendedSkillCount +
                            ", hasAdminStatus=" + hasAdminStatus,
                    System.currentTimeMillis() - start);
        } catch (Exception e) {
            record(id, "Extended Agent Card", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static int countJsonArrayItems(String json, String arrayKey) {
        int keyIndex = json.indexOf(arrayKey);
        if (keyIndex == -1) return 0;
        int arrayStart = json.indexOf("[", keyIndex);
        if (arrayStart == -1) return 0;
        
        // Find matching closing bracket
        int depth = 0;
        int arrayEnd = -1;
        boolean inString = false;
        char prevChar = ' ';
        
        for (int i = arrayStart; i < json.length(); i++) {
            char c = json.charAt(i);
            
            if (c == '"' && prevChar != '\\') {
                inString = !inString;
            }
            
            if (!inString) {
                if (c == '[') depth++;
                if (c == ']') {
                    depth--;
                    if (depth == 0) {
                        arrayEnd = i;
                        break;
                    }
                }
            }
            
            prevChar = c;
        }
        
        if (arrayEnd == -1) return 0;
        String arrayContent = json.substring(arrayStart + 1, arrayEnd);
        if (arrayContent.trim().isEmpty()) return 0;
        
        // Count objects by counting opening braces at depth 0
        int count = 0;
        depth = 0;
        inString = false;
        prevChar = ' ';
        
        for (int i = 0; i < arrayContent.length(); i++) {
            char c = arrayContent.charAt(i);
            
            if (c == '"' && prevChar != '\\') {
                inString = !inString;
            }
            
            if (!inString) {
                if (c == '{') {
                    if (depth == 0) count++;
                    depth++;
                }
                if (c == '}') {
                    depth--;
                }
            }
            
            prevChar = c;
        }
        return count;
    }

    static void testEchoSendMessage(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, false);
            var result = new CompletableFuture<String>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof MessageEvent me)
                            result.complete(extractText(me.getMessage()));
                        else if (event instanceof TaskEvent te
                                && te.getTask().status().state().isFinal())
                            result.complete(extractArtifactText(te.getTask()));
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("hello from Java SDK"));
                String text = result.get(10, TimeUnit.SECONDS);
                boolean ok = text.toLowerCase().contains("hello from java sdk");
                record(id, "Echo Send Message", ok, "text=" + text,
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Echo Send Message", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecMessageOnly(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var result = new CompletableFuture<ClientEvent>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> result.complete(event))
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("message-only hello"));
                ClientEvent event = result.get(10, TimeUnit.SECONDS);
                boolean isMessage = event instanceof MessageEvent;
                record(id, "Message Only", isMessage,
                        "eventType=" + event.getClass().getSimpleName(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Message Only", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecTaskLifecycle(String lifecycleId, String getTaskId,
                                      String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var result = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-lifecycle process this"));
                Task task = result.get(10, TimeUnit.SECONDS);
                String taskId = task.id();
                boolean ok = task.status().state() == TaskState.TASK_STATE_COMPLETED
                        && task.artifacts() != null && !task.artifacts().isEmpty();
                record(lifecycleId, "Task Lifecycle", ok,
                        "state=" + task.status().state() + ", artifacts=" +
                                (task.artifacts() != null ? task.artifacts().size() : 0),
                        System.currentTimeMillis() - start);

                // GetTask
                long start2 = System.currentTimeMillis();
                try {
                    Task fetched = client.getTask(new TaskQueryParams(taskId));
                    record(getTaskId, "GetTask", fetched.id().equals(taskId),
                            "state=" + fetched.status().state(),
                            System.currentTimeMillis() - start2);
                } catch (Exception e2) {
                    record(getTaskId, "GetTask", false, exDetail(e2),
                            System.currentTimeMillis() - start2);
                }
            }
        } catch (Exception e) {
            record(lifecycleId, "Task Lifecycle", false, exDetail(e),
                    System.currentTimeMillis() - start);
            record(getTaskId, "GetTask", false, "skipped", 0);
        }
    }

    static void testSpecTaskFailure(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var result = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_FAILED)
                            result.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_FAILED)
                            result.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-failure trigger error"));
                Task task = result.get(10, TimeUnit.SECONDS);
                record(id, "Task Failure", task.status().state() == TaskState.TASK_STATE_FAILED,
                        "state=" + task.status().state(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Task Failure", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecDataTypes(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var result = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("data-types show all"));
                Task task = result.get(10, TimeUnit.SECONDS);
                boolean hasText = false, hasData = false, hasFile = false;
                if (task.artifacts() != null) {
                    for (Artifact a : task.artifacts()) {
                        for (Part<?> p : a.parts()) {
                            if (p instanceof TextPart) hasText = true;
                            if (p instanceof DataPart) hasData = true;
                            if (p instanceof FilePart) hasFile = true;
                        }
                    }
                }
                record(id, "Data Types", hasText && hasData && hasFile,
                        "text=" + hasText + ", data=" + hasData + ", file=" + hasFile,
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Data Types", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecStreaming(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var events = new CopyOnWriteArrayList<ClientEvent>();
            var done = new CompletableFuture<Void>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        events.add(event);
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                        if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                    })
                    .streamingErrorHandler(e -> done.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("streaming generate output"));
                done.get(15, TimeUnit.SECONDS);
                boolean ok = events.size() >= 3;
                record(id, "Streaming", ok,
                        "events=" + events.size(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Streaming", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecMultiTurn(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var step1 = new CompletableFuture<Task>();

            // Step 1: start multi-turn
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        Task t = extractTask(event);
                        if (t != null && t.status().state().isFinal()
                                || t != null && t.status().state() == TaskState.TASK_STATE_INPUT_REQUIRED)
                            step1.complete(t);
                    })
                    .streamingErrorHandler(e -> step1.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("multi-turn start conversation"));
                Task t1 = step1.get(10, TimeUnit.SECONDS);

                if (t1.status().state() != TaskState.TASK_STATE_INPUT_REQUIRED) {
                    record(id, "Multi-Turn", false,
                            "step1 expected INPUT_REQUIRED, got " + t1.status().state(),
                            System.currentTimeMillis() - start);
                    return;
                }

                // Step 2: follow-up
                var step2 = new CompletableFuture<Task>();
                try (Client client2 = tc.apply(Client.builder(card))
                        .addConsumer((event, c) -> {
                            Task t = extractTask(event);
                            if (t != null && t.status().state().isFinal()
                                    || t != null && t.status().state() == TaskState.TASK_STATE_INPUT_REQUIRED)
                                step2.complete(t);
                        })
                        .streamingErrorHandler(e -> step2.completeExceptionally(e))
                        .build()) {

                    Message followUp = A2A.createUserTextMessage("more data", t1.contextId(), t1.id());
                    client2.sendMessage(followUp);
                    Task t2 = step2.get(10, TimeUnit.SECONDS);

                    if (t2.status().state() != TaskState.TASK_STATE_INPUT_REQUIRED) {
                        record(id, "Multi-Turn", false,
                                "step2 expected INPUT_REQUIRED, got " + t2.status().state(),
                                System.currentTimeMillis() - start);
                        return;
                    }

                    // Step 3: done
                    var step3 = new CompletableFuture<Task>();
                    try (Client client3 = tc.apply(Client.builder(card))
                            .addConsumer((event, c) -> {
                                Task t = extractTask(event);
                                if (t != null && t.status().state() == TaskState.TASK_STATE_COMPLETED)
                                    step3.complete(t);
                            })
                            .streamingErrorHandler(e -> step3.completeExceptionally(e))
                            .build()) {

                        Message doneMsg = A2A.createUserTextMessage("done", t1.contextId(), t1.id());
                        client3.sendMessage(doneMsg);
                        Task t3 = step3.get(10, TimeUnit.SECONDS);

                        boolean ok = t3.status().state() == TaskState.TASK_STATE_COMPLETED;
                        record(id, "Multi-Turn", ok,
                                "step1=INPUT_REQUIRED, step2=INPUT_REQUIRED, step3=" + t3.status().state(),
                                System.currentTimeMillis() - start);
                    }
                }
            }
        } catch (Exception e) {
            record(id, "Multi-Turn", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecTaskCancel(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskIdFuture = new CompletableFuture<String>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te)
                            taskIdFuture.complete(te.getTask().id());
                        else if (event instanceof TaskUpdateEvent tue)
                            taskIdFuture.complete(tue.getTask().id());
                    })
                    .streamingErrorHandler(e -> taskIdFuture.completeExceptionally(e))
                    .build()) {

                // Send async — the handler stays working for 30s
                new Thread(() -> {
                    try { client.sendMessage(A2A.toUserMessage("task-cancel")); }
                    catch (Exception ignored) {}
                }).start();

                String taskId = taskIdFuture.get(10, TimeUnit.SECONDS);

                // Now cancel it
                Task canceled = client.cancelTask(new CancelTaskParams(taskId));
                boolean ok = canceled.status().state() == TaskState.TASK_STATE_CANCELED;
                record(id, "Task Cancel", ok,
                        "taskId=" + taskId + ", state=" + canceled.status().state(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Task Cancel", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecCancelWithMetadata(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskIdFuture = new CompletableFuture<String>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te)
                            taskIdFuture.complete(te.getTask().id());
                        else if (event instanceof TaskUpdateEvent tue)
                            taskIdFuture.complete(tue.getTask().id());
                    })
                    .streamingErrorHandler(e -> taskIdFuture.completeExceptionally(e))
                    .build()) {

                // Send async — the agent keeps the task in WORKING state
                new Thread(() -> {
                    try { client.sendMessage(A2A.toUserMessage("task-cancel start")); }
                    catch (Exception ignored) {}
                }).start();

                String taskId = taskIdFuture.get(10, TimeUnit.SECONDS);

                // Beta1-SNAPSHOT: CancelTaskParams supports metadata
                var cancelParams = new CancelTaskParams(taskId, "", Map.of(
                        "reason", "test-cancel-reason",
                        "requestedBy", "java-sdk"));
                Task canceled = client.cancelTask(cancelParams);

                boolean stateOk = canceled.status().state() == TaskState.TASK_STATE_CANCELED;

                Map<String, Object> respMeta = canceled.metadata();
                boolean metaOk = respMeta != null
                        && "test-cancel-reason".equals(String.valueOf(respMeta.get("reason")))
                        && "java-sdk".equals(String.valueOf(respMeta.get("requestedBy")));

                String detail;
                if (!stateOk) {
                    detail = "taskId=" + taskId + ", state=" + canceled.status().state()
                            + " (expected CANCELED)";
                } else if (!metaOk) {
                    detail = "taskId=" + taskId + ", state=CANCELED"
                            + ", metadata not echoed (reason/requestedBy not in response)";
                } else {
                    detail = "taskId=" + taskId + ", state=CANCELED, metadata verified";
                }

                record(id, "Cancel With Metadata", stateOk && metaOk, detail,
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Cancel With Metadata", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecListTasks(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .build()) {

                var result = client.listTasks(new ListTasksParams());
                int count = result.tasks() != null ? result.tasks().size() : 0;
                record(id, "List Tasks", count >= 1,
                        "count=" + count,
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "List Tasks", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSpecReturnImmediately(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var result = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te) result.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue) result.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                // SDK may not expose returnImmediately/blocking — just measure time
                client.sendMessage(A2A.toUserMessage("long-running test"));
                Task task = result.get(15, TimeUnit.SECONDS);
                long elapsed = System.currentTimeMillis() - start;
                boolean ok = elapsed < 3000;
                String detail = ok ? "fast response, state=" + task.status().state() + ", took=" + elapsed + "ms"
                        : "returnImmediately ignored by SDK, took " + elapsed + "ms";
                record(id, "Return Immediately", ok, detail, elapsed);
            }
        } catch (Exception e) {
            record(id, "Return Immediately", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorTaskNotFound(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .build()) {

                client.getTask(new TaskQueryParams("00000000-0000-0000-0000-000000000000"));
                record(id, "Task Not Found", false, "should have thrown",
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Task Not Found", true,
                    "error=" + e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 80),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorCancelNotFound(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .build()) {
                client.cancelTask(new CancelTaskParams("00000000-0000-0000-0000-000000000000"));
                record(id, "Cancel Not Found", false, "expected error, got success",
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Cancel Not Found", true,
                    "error=" + e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 80),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorCancelTerminal(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskFuture = new CompletableFuture<Task>();
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> taskFuture.completeExceptionally(e))
                    .build()) {
                client.sendMessage(A2A.toUserMessage("task-lifecycle process this"));
                Task task = taskFuture.get(10, TimeUnit.SECONDS);
                try {
                    client.cancelTask(new CancelTaskParams(task.id()));
                    record(id, "Cancel Terminal Task", false, "expected error, got success",
                            System.currentTimeMillis() - start);
                } catch (Exception cancelEx) {
                    record(id, "Cancel Terminal Task", true,
                            "got expected error: " + exDetail(cancelEx),
                            System.currentTimeMillis() - start);
                }
            }
        } catch (Exception e) {
            record(id, "Cancel Terminal Task", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorSendTerminal(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskFuture = new CompletableFuture<Task>();
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> taskFuture.completeExceptionally(e))
                    .build()) {
                client.sendMessage(A2A.toUserMessage("task-lifecycle process this"));
                Task task = taskFuture.get(10, TimeUnit.SECONDS);
                try {
                    client.sendMessage(A2A.createUserTextMessage("this should fail", null, task.id()));
                    record(id, "Send Terminal Task", false, "expected error, got success",
                            System.currentTimeMillis() - start);
                } catch (Exception sendEx) {
                    record(id, "Send Terminal Task", true,
                            "got expected error: " + exDetail(sendEx),
                            System.currentTimeMillis() - start);
                }
            }
        } catch (Exception e) {
            record(id, "Send Terminal Task", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorSendInvalidTask(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .streamingErrorHandler(e -> {})
                    .build()) {
                client.sendMessage(A2A.createUserTextMessage("test", null,
                        "00000000-0000-0000-0000-000000000000"));
                record(id, "Send Invalid Task", false, "expected error, got success",
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Send Invalid Task", true,
                    "error=" + e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 80),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorPushNotSupported(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .build()) {
                var config = new TaskPushNotificationConfig(
                        "push-config-1", "00000000-0000-0000-0000-000000000000",
                        "https://example.com/webhook", null, null, null);
                client.createTaskPushNotificationConfiguration(config);
                record(id, "Push Not Supported", false, "expected error, got success",
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Push Not Supported", true,
                    "error=" + e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 80),
                    System.currentTimeMillis() - start);
        }
    }

    static void testSubscribeToTask(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskIdFuture = new CompletableFuture<String>();

            // Start a WORKING task (task-cancel stays working for 30s)
            try (Client sendClient = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te)
                            taskIdFuture.complete(te.getTask().id());
                        else if (event instanceof TaskUpdateEvent tue)
                            taskIdFuture.complete(tue.getTask().id());
                    })
                    .streamingErrorHandler(e -> taskIdFuture.completeExceptionally(e))
                    .build()) {

                new Thread(() -> {
                    try { sendClient.sendMessage(A2A.toUserMessage("task-cancel")); }
                    catch (Exception ignored) {}
                }).start();

                String taskId = taskIdFuture.get(10, TimeUnit.SECONDS);

                // Subscribe from a second client
                var subEvent = new CompletableFuture<ClientEvent>();
                BiConsumer<ClientEvent, AgentCard> subConsumer = (event, c) -> subEvent.complete(event);
                Consumer<Throwable> subErrorHandler = e -> subEvent.completeExceptionally(e);
                try (Client subClient = tc.apply(Client.builder(card))
                        .addConsumer(subConsumer)
                        .streamingErrorHandler(subErrorHandler)
                        .build()) {

                    new Thread(() -> {
                        try { subClient.subscribeToTask(new TaskIdParams(taskId), List.of(subConsumer), subErrorHandler, null); }
                        catch (Exception ignored) {}
                    }).start();

                    // Allow subscription to establish, then cancel to trigger events
                    Thread.sleep(500);
                    sendClient.cancelTask(new CancelTaskParams(taskId));

                    ClientEvent event = subEvent.get(10, TimeUnit.SECONDS);
                    record(id, "Subscribe To Task", event != null,
                            "eventType=" + event.getClass().getSimpleName(),
                            System.currentTimeMillis() - start);
                }
            }
        } catch (Exception e) {
            record(id, "Subscribe To Task", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testErrorSubscribeNotFound(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {})
                    .build()) {
                client.subscribeToTask(new TaskIdParams("00000000-0000-0000-0000-000000000000"),
                        List.of((event, c) -> {}), null, null);
                record(id, "Subscribe Not Found", false, "expected error, got success",
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Subscribe Not Found", true,
                    "error=" + e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 80),
                    System.currentTimeMillis() - start);
        }
    }

    static void testStreamMessageOnly(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var events = new CopyOnWriteArrayList<ClientEvent>();
            var done = new CompletableFuture<Void>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        events.add(event);
                        if (event instanceof MessageEvent) done.complete(null);
                        if (event instanceof TaskEvent) done.complete(null);
                    })
                    .streamingErrorHandler(e -> done.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("message-only hello"));
                done.get(10, TimeUnit.SECONDS);
                Thread.sleep(500);
                long msgCount = events.stream().filter(e -> e instanceof MessageEvent).count();
                boolean ok = msgCount == 1;
                record(id, "Stream Message Only", ok,
                        "messageEvents=" + msgCount + ", totalEvents=" + events.size(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Stream Message Only", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testStreamTaskLifecycle(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var events = new CopyOnWriteArrayList<ClientEvent>();
            var done = new CompletableFuture<Void>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        events.add(event);
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                        if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                    })
                    .streamingErrorHandler(e -> done.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-lifecycle process"));
                done.get(15, TimeUnit.SECONDS);
                boolean hasTaskEvent = events.stream().anyMatch(e ->
                        e instanceof TaskEvent || e instanceof TaskUpdateEvent);
                ClientEvent last = events.get(events.size() - 1);
                boolean terminal = false;
                if (last instanceof TaskEvent te)
                    terminal = te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED;
                if (last instanceof TaskUpdateEvent tue)
                    terminal = tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED;
                boolean ok = hasTaskEvent && terminal;
                record(id, "Stream Task Lifecycle", ok,
                        "events=" + events.size() + ", hasTask=" + hasTaskEvent + ", terminal=" + terminal,
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Stream Task Lifecycle", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testMultiTurnContextPreserved(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var step1 = new CompletableFuture<Task>();

            // Step 1: start multi-turn
            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        Task t = extractTask(event);
                        if (t != null && t.status().state().isFinal()
                                || t != null && t.status().state() == TaskState.TASK_STATE_INPUT_REQUIRED)
                            step1.complete(t);
                    })
                    .streamingErrorHandler(e -> step1.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("multi-turn start conversation"));
                Task t1 = step1.get(10, TimeUnit.SECONDS);
                String contextId = t1.contextId();
                String taskId = t1.id();

                // Step 2: follow-up with taskId, verify same contextId
                var step2 = new CompletableFuture<Task>();
                try (Client client2 = tc.apply(Client.builder(card))
                        .addConsumer((event, c) -> {
                            Task t = extractTask(event);
                            if (t != null && t.status().state().isFinal()
                                    || t != null && t.status().state() == TaskState.TASK_STATE_INPUT_REQUIRED)
                                step2.complete(t);
                        })
                        .streamingErrorHandler(e -> step2.completeExceptionally(e))
                        .build()) {

                    Message followUp = A2A.createUserTextMessage("follow up", contextId, taskId);
                    client2.sendMessage(followUp);
                    Task t2 = step2.get(10, TimeUnit.SECONDS);
                    boolean sameContext = contextId != null && contextId.equals(t2.contextId());
                    record(id, "Multi-Turn Context Preserved", sameContext,
                            "ctx1=" + contextId + ", ctx2=" + t2.contextId(),
                            System.currentTimeMillis() - start);
                }
            }
        } catch (Exception e) {
            record(id, "Multi-Turn Context Preserved", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testGetTaskWithHistory(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskFuture = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> taskFuture.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-lifecycle process this"));
                Task task = taskFuture.get(10, TimeUnit.SECONDS);
                Task fetched = client.getTask(new TaskQueryParams(task.id(), 10));
                boolean ok = fetched.id().equals(task.id());
                record(id, "Get Task With History", ok,
                        "taskId=" + fetched.id() + ", state=" + fetched.status().state(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Get Task With History", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testGetTaskAfterFailure(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, true);
            var taskFuture = new CompletableFuture<Task>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_FAILED)
                            taskFuture.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_FAILED)
                            taskFuture.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> taskFuture.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-failure trigger error"));
                Task task = taskFuture.get(10, TimeUnit.SECONDS);
                Task fetched = client.getTask(new TaskQueryParams(task.id()));
                boolean ok = fetched.status().state() == TaskState.TASK_STATE_FAILED;
                record(id, "Get Task After Failure", ok,
                        "taskId=" + fetched.id() + ", state=" + fetched.status().state(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "Get Task After Failure", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    // ── v0.3 Backward Compatibility Tests ───────────────────────────

    static void runV03Tests(String baseUrl) {
        String spec03Url = baseUrl + "/spec03";

        testV03AgentCard("v03/spec03-agent-card", spec03Url);
        testV03SendMessage("v03/spec03-send-message", spec03Url);
        testV03TaskLifecycle("v03/spec03-task-lifecycle", spec03Url);
        testV03Streaming("v03/spec03-streaming", spec03Url);
    }

    static void testV03AgentCard(String id, String agentUrl) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = A2A.getAgentCard(agentUrl, null, Map.of());
            boolean hasProtocolVersion = "0.3.0".equals(card.version());
            boolean hasUrl = card.supportedInterfaces() != null
                    && card.supportedInterfaces().stream()
                            .anyMatch(i -> i.url() != null && !i.url().isEmpty());
            boolean ok = hasProtocolVersion && hasUrl;
            record(id, "v0.3 Agent Card", ok,
                    "protocolVersion=0.3.0=" + hasProtocolVersion
                            + ", hasUrl=" + hasUrl,
                    System.currentTimeMillis() - start);
        } catch (Exception e) {
            record(id, "v0.3 Agent Card", false, exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static AgentCard buildV03Card(String agentUrl) {
        return AgentCard.builder()
                .name("v0.3 Spec Agent")
                .description("Manually constructed card for v0.3 agent")
                .version("0.3.0")
                .supportedInterfaces(List.of(
                        new AgentInterface("JSONRPC", agentUrl, "", "0.3.0"),
                        new AgentInterface("HTTP+JSON", agentUrl + "/v1", "", "0.3.0")))
                .capabilities(new AgentCapabilities(true, false, false, List.of()))
                .defaultInputModes(List.of("text/plain"))
                .defaultOutputModes(List.of("text/plain"))
                .skills(List.of())
                .build();
    }

    static AgentCard getV03Card(String agentUrl) {
        try {
            return A2A.getAgentCard(agentUrl, null, Map.of());
        } catch (Exception e) {
            System.out.println("    ⚠ SDK v0.3 card fetch failed, using manual card: " + e.getMessage());
            return buildV03Card(agentUrl);
        }
    }

    static TransportConfigurer v03Jsonrpc() {
        return b -> b.withTransport(JSONRPCTransport.class,
                new JSONRPCTransportConfigBuilder());
    }

    static void testV03SendMessage(String id, String agentUrl) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getV03Card(agentUrl);
            var result = new CompletableFuture<ClientEvent>();

            try (Client client = v03Jsonrpc().apply(Client.builder(card))
                    .addConsumer((event, c) -> result.complete(event))
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("message-only hello"));
                ClientEvent event = result.get(15, TimeUnit.SECONDS);
                boolean isMessage = event instanceof MessageEvent;
                record(id, "v0.3 Send Message", isMessage,
                        "eventType=" + event.getClass().getSimpleName(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "v0.3 Send Message", false,
                    "SDK may not support v0.3 fallback: " + exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testV03TaskLifecycle(String id, String agentUrl) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getV03Card(agentUrl);
            var result = new CompletableFuture<Task>();

            try (Client client = v03Jsonrpc().apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            result.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> result.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("task-lifecycle process"));
                Task task = result.get(15, TimeUnit.SECONDS);
                boolean ok = task.status().state() == TaskState.TASK_STATE_COMPLETED
                        && task.artifacts() != null && !task.artifacts().isEmpty();
                record(id, "v0.3 Task Lifecycle", ok,
                        "state=" + task.status().state() + ", artifacts=" +
                                (task.artifacts() != null ? task.artifacts().size() : 0),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "v0.3 Task Lifecycle", false,
                    "SDK may not support v0.3 fallback: " + exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    static void testV03Streaming(String id, String agentUrl) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getV03Card(agentUrl);
            var events = new CopyOnWriteArrayList<ClientEvent>();
            var done = new CompletableFuture<Void>();

            try (Client client = v03Jsonrpc().apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        events.add(event);
                        if (event instanceof TaskEvent te
                                && te.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                        if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            done.complete(null);
                    })
                    .streamingErrorHandler(e -> done.completeExceptionally(e))
                    .build()) {

                client.sendMessage(A2A.toUserMessage("streaming generate"));
                done.get(15, TimeUnit.SECONDS);
                boolean ok = events.size() >= 3;
                record(id, "v0.3 Streaming", ok,
                        "events=" + events.size(),
                        System.currentTimeMillis() - start);
            }
        } catch (Exception e) {
            record(id, "v0.3 Streaming", false,
                    "SDK may not support v0.3 fallback: " + exDetail(e),
                    System.currentTimeMillis() - start);
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────

    static Task extractTask(ClientEvent event) {
        if (event instanceof TaskEvent te) return te.getTask();
        if (event instanceof TaskUpdateEvent tue) return tue.getTask();
        return null;
    }

    static String extractText(Message msg) {
        if (msg == null || msg.parts() == null) return "";
        StringBuilder sb = new StringBuilder();
        for (Part<?> p : msg.parts()) {
            if (p instanceof TextPart tp) sb.append(tp.text());
        }
        return sb.toString();
    }

    static String extractArtifactText(Task task) {
        if (task == null || task.artifacts() == null) return "";
        StringBuilder sb = new StringBuilder();
        for (Artifact a : task.artifacts()) {
            for (Part<?> p : a.parts()) {
                if (p instanceof TextPart tp) sb.append(tp.text());
            }
        }
        return sb.toString();
    }

    static String exDetail(Exception e) {
        Throwable cause = e.getCause() != null ? e.getCause() : e;
        return cause.getClass().getSimpleName() + ": " + truncate(cause.getMessage(), 120);
    }

    static String truncate(String s, int max) {
        if (s == null) return "null";
        return s.length() > max ? s.substring(0, max) + "..." : s;
    }

    static String detectSdkVersion() {
        try {
            String pom = Files.readString(Path.of("pom.xml"));
            Matcher m = Pattern.compile("<a2a\\.version>([^<]+)</a2a\\.version>").matcher(pom);
            if (m.find()) return "a2a-java-sdk " + m.group(1);
        } catch (Exception e) { /* fall through */ }
        return "a2a-java-sdk unknown";
    }

    static void writeResultsJson(String baseUrl) throws IOException {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"client\": \"java\",\n");
        sb.append("  \"sdk\": \"").append(detectSdkVersion()).append("\",\n");
        sb.append("  \"protocolVersion\": \"1.0\",\n");
        sb.append("  \"timestamp\": \"").append(Instant.now()).append("\",\n");
        sb.append("  \"baseUrl\": \"").append(baseUrl).append("\",\n");
        sb.append("  \"results\": [\n");
        for (int i = 0; i < results.size(); i++) {
            TestResult r = results.get(i);
            sb.append("    {\"id\":\"").append(r.id)
              .append("\",\"name\":\"").append(r.name)
              .append("\",\"passed\":").append(r.passed)
              .append(",\"detail\":\"").append(r.detail.replace("\\", "\\\\").replace("\"", "'").replace("\n", " ").replace("\r", ""))
              .append("\",\"durationMs\":").append(r.durationMs).append("}");
            if (i < results.size() - 1) sb.append(",");
            sb.append("\n");
        }
        sb.append("  ]\n}\n");
        Files.writeString(Path.of("results.json"), sb.toString());
        System.out.println("\nResults written to results.json");
    }
}
