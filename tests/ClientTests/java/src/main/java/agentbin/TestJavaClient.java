package agentbin;

import io.a2a.A2A;
import io.a2a.client.Client;
import io.a2a.client.ClientBuilder;
import io.a2a.client.ClientEvent;
import io.a2a.client.MessageEvent;
import io.a2a.client.TaskEvent;
import io.a2a.client.TaskUpdateEvent;
import io.a2a.client.transport.jsonrpc.JSONRPCTransport;
import io.a2a.client.transport.jsonrpc.JSONRPCTransportConfigBuilder;
import io.a2a.client.transport.rest.RestTransport;
import io.a2a.client.transport.rest.RestTransportConfigBuilder;
import io.a2a.client.transport.spi.interceptors.ClientCallInterceptor;
import io.a2a.client.transport.spi.interceptors.ClientCallContext;
import io.a2a.client.transport.spi.interceptors.PayloadAndHeaders;
import io.a2a.spec.*;

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
        testEchoSendMessage(binding + "/echo-send-message", echoUrl, tc);
        testSpecMessageOnly(binding + "/spec-message-only", specUrl, tc);
        testSpecTaskLifecycle(binding + "/spec-task-lifecycle", binding + "/spec-get-task", specUrl, tc);
        testSpecTaskFailure(binding + "/spec-task-failure", specUrl, tc);
        testSpecDataTypes(binding + "/spec-data-types", specUrl, tc);
        testSpecStreaming(binding + "/spec-streaming", specUrl, tc);
        testSpecMultiTurn(binding + "/spec-multi-turn", specUrl, tc);
        testSpecTaskCancel(binding + "/spec-task-cancel", specUrl, tc);
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

    static void testEchoSendMessage(String id, String agentUrl, TransportConfigurer tc) {
        long start = System.currentTimeMillis();
        try {
            AgentCard card = getCard(agentUrl, false);
            var result = new CompletableFuture<String>();

            try (Client client = tc.apply(Client.builder(card))
                    .addConsumer((event, c) -> {
                        if (event instanceof MessageEvent me)
                            result.complete(extractText(me.getMessage()));
                        else if (event instanceof TaskEvent te)
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
                        if (event instanceof TaskEvent te)
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
                        if (event instanceof TaskEvent te)
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
                        if (event instanceof TaskEvent te)
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
                        if (event instanceof TaskEvent te) step1.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue) step1.complete(tue.getTask());
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
                            if (event instanceof TaskEvent te) step2.complete(te.getTask());
                            else if (event instanceof TaskUpdateEvent tue) step2.complete(tue.getTask());
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
                                if (event instanceof TaskEvent te) step3.complete(te.getTask());
                                else if (event instanceof TaskUpdateEvent tue) step3.complete(tue.getTask());
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
                Task canceled = client.cancelTask(new TaskIdParams(taskId));
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
                boolean ok = elapsed < 3000
                        && task.status().state() != TaskState.TASK_STATE_COMPLETED;
                String detail = ok ? "fast response"
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
                client.cancelTask(new TaskIdParams("00000000-0000-0000-0000-000000000000"));
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
                        if (event instanceof TaskEvent te) taskFuture.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue
                                && tue.getTask().status().state() == TaskState.TASK_STATE_COMPLETED)
                            taskFuture.complete(tue.getTask());
                    })
                    .streamingErrorHandler(e -> taskFuture.completeExceptionally(e))
                    .build()) {
                client.sendMessage(A2A.toUserMessage("task-lifecycle process this"));
                Task task = taskFuture.get(10, TimeUnit.SECONDS);
                try {
                    client.cancelTask(new TaskIdParams(task.id()));
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
                        if (event instanceof TaskEvent te) taskFuture.complete(te.getTask());
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
                var pushConfig = PushNotificationConfig.builder()
                        .url("https://example.com/webhook")
                        .build();
                var config = new TaskPushNotificationConfig(
                        "00000000-0000-0000-0000-000000000000", pushConfig, null);
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
                try (Client subClient = tc.apply(Client.builder(card))
                        .addConsumer((event, c) -> subEvent.complete(event))
                        .streamingErrorHandler(e -> subEvent.completeExceptionally(e))
                        .build()) {

                    new Thread(() -> {
                        try { subClient.subscribeToTask(new TaskIdParams(taskId)); }
                        catch (Exception ignored) {}
                    }).start();

                    // Allow subscription to establish, then cancel to trigger events
                    Thread.sleep(500);
                    sendClient.cancelTask(new TaskIdParams(taskId));

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
                client.subscribeToTask(new TaskIdParams("00000000-0000-0000-0000-000000000000"));
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
                        if (event instanceof TaskEvent te) step1.complete(te.getTask());
                        else if (event instanceof TaskUpdateEvent tue) step1.complete(tue.getTask());
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
                            if (event instanceof TaskEvent te) step2.complete(te.getTask());
                            else if (event instanceof TaskUpdateEvent tue) step2.complete(tue.getTask());
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
                        if (event instanceof TaskEvent te) taskFuture.complete(te.getTask());
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
                        if (event instanceof TaskEvent te) taskFuture.complete(te.getTask());
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
            var httpClient = HttpClient.newHttpClient();
            var request = HttpRequest.newBuilder()
                    .uri(URI.create(agentUrl + "/.well-known/agent-card.json"))
                    .GET()
                    .build();
            var response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            String body = response.body();
            int status = response.statusCode();

            boolean hasProtocolVersion = body.contains("\"protocolVersion\"")
                    && body.contains("\"0.3.0\"");
            boolean hasUrl = body.contains("\"url\"");
            boolean ok = status == 200 && hasProtocolVersion && hasUrl;
            record(id, "v0.3 Agent Card", ok,
                    "status=" + status + ", protocolVersion=0.3.0=" + hasProtocolVersion
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
                        if (event instanceof TaskEvent te)
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

    static void writeResultsJson(String baseUrl) throws IOException {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"client\": \"java\",\n");
        sb.append("  \"sdk\": \"a2a-java-sdk 1.0.0.Alpha3\",\n");
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
