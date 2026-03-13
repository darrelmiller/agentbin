import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;

/**
 * Single-file Java A2A client test against deployed agentbin service.
 * Uses raw java.net.http.HttpClient — no build system needed.
 * Run: java TestJavaClient.java
 */
public class TestJavaClient {

    static final String BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";
    static final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .build();

    static int passed = 0, failed = 0;
    static List<String[]> results = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        System.out.println("=== Java A2A Client Test Suite ===");
        System.out.println("Target: " + BASE);
        System.out.println();

        // Agent card tests
        testAgentCard("echo");
        testAgentCard("spec");

        // Echo agent: message-only (no skill prefix)
        testSendMessage("echo", "message-only", "hello from java", true);

        // Spec agent skills
        testSendMessage("spec", "message-only", "message-only hello from java", false);
        testSendMessage("spec", "task-lifecycle", "task-lifecycle hello from java", false);
        testSendMessage("spec", "task-failure", "task-failure hello from java", false);
        testSendMessage("spec", "data-types", "data-types hello from java", false);

        // Print summary
        System.out.println();
        System.out.println("=== RESULTS SUMMARY ===");
        System.out.printf("%-12s %-20s %-8s %s%n", "Agent", "Test", "Result", "Details");
        System.out.println("-".repeat(80));
        for (String[] r : results) {
            System.out.printf("%-12s %-20s %-8s %s%n", r[0], r[1], r[2], r[3]);
        }
        System.out.println("-".repeat(80));
        System.out.printf("Total: %d passed, %d failed, %d total%n", passed, failed, passed + failed);

        System.exit(failed > 0 ? 1 : 0);
    }

    static void testAgentCard(String agent) {
        String testName = "agent-card";
        String url = BASE + "/" + agent + "/.well-known/agent-card.json";
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .GET()
                    .timeout(Duration.ofSeconds(15))
                    .build();
            HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());

            if (resp.statusCode() != 200) {
                record(agent, testName, false, "HTTP " + resp.statusCode());
                return;
            }

            String body = resp.body();
            // Basic validation: should contain agent name and URL
            boolean hasName = body.contains("\"name\"");
            boolean hasUrl = body.contains("\"url\"");
            boolean hasSkills = body.contains("\"skills\"");

            if (hasName && hasUrl) {
                // Extract agent name from JSON (simple parsing)
                String name = extractJsonString(body, "name");
                String detail = "name=" + name + ", hasSkills=" + hasSkills;
                record(agent, testName, true, detail);
            } else {
                record(agent, testName, false, "Missing required fields");
            }
        } catch (Exception e) {
            record(agent, testName, false, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    static void testSendMessage(String agent, String testName, String text, boolean isEcho) {
        String url = BASE + "/" + agent;
        String msgId = UUID.randomUUID().toString();
        String rpcId = UUID.randomUUID().toString();

        // Build JSON-RPC request
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

        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(30))
                    .build();

            System.out.printf(">> %s/%s: sending '%s'...%n", agent, testName, text);
            HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());

            if (resp.statusCode() != 200) {
                record(agent, testName, false, "HTTP " + resp.statusCode() + ": " + truncate(resp.body(), 100));
                return;
            }

            String body = resp.body();

            // Check for JSON-RPC error
            if (body.contains("\"error\"") && !body.contains("\"result\"")) {
                String errMsg = extractJsonString(body, "message");
                record(agent, testName, false, "JSON-RPC error: " + errMsg);
                return;
            }

            // Check for result
            if (!body.contains("\"result\"")) {
                record(agent, testName, false, "No result in response: " + truncate(body, 100));
                return;
            }

            // Extract response text from nested result.message.parts[].text
            String responseText = extractResponseText(body);

            // Validate based on test type
            if (isEcho) {
                // Echo should return our text back
                boolean echoed = responseText != null && responseText.contains("hello from java");
                record(agent, testName, echoed,
                        echoed ? "echo=" + truncate(responseText, 60) : "unexpected: " + truncate(responseText, 60));
            } else if (testName.equals("task-failure")) {
                // task-failure should return an error in the task status or JSON-RPC error
                // The spec agent returns a task with status FAILED
                boolean hasFailed = body.contains("\"TASK_STATE_FAILED\"") || body.contains("failed")
                        || body.contains("\"error\"");
                record(agent, testName, hasFailed,
                        hasFailed ? "Got expected failure indicator"
                                : "response=" + truncate(responseText != null ? responseText : body, 80));
            } else {
                // For other skills, just check we got a valid response with text
                boolean hasText = responseText != null && !responseText.isEmpty();
                record(agent, testName, hasText,
                        hasText ? "text=" + truncate(responseText, 60) : "no text in response");
            }
        } catch (Exception e) {
            record(agent, testName, false, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    static void record(String agent, String test, boolean pass, String detail) {
        if (pass) {
            passed++;
            System.out.println("  PASS: " + agent + "/" + test + " — " + detail);
        } else {
            failed++;
            System.out.println("  FAIL: " + agent + "/" + test + " — " + detail);
        }
        results.add(new String[] { agent, test, pass ? "PASS" : "FAIL", detail });
    }

    // Simple JSON string extraction (avoids needing a JSON library)
    static String extractJsonString(String json, String key) {
        String pattern = "\"" + key + "\"";
        int idx = json.indexOf(pattern);
        if (idx < 0) return null;
        int colonIdx = json.indexOf(':', idx + pattern.length());
        if (colonIdx < 0) return null;
        int quoteStart = json.indexOf('"', colonIdx + 1);
        if (quoteStart < 0) return null;
        int quoteEnd = json.indexOf('"', quoteStart + 1);
        // Handle escaped quotes
        while (quoteEnd > 0 && json.charAt(quoteEnd - 1) == '\\') {
            quoteEnd = json.indexOf('"', quoteEnd + 1);
        }
        if (quoteEnd < 0) return null;
        return json.substring(quoteStart + 1, quoteEnd);
    }

    // Extract text from response JSON — finds first "text" value inside parts array
    static String extractResponseText(String json) {
        // Look for "parts" then find "text" within it
        int partsIdx = json.indexOf("\"parts\"");
        if (partsIdx < 0) return extractJsonString(json, "text");
        String afterParts = json.substring(partsIdx);
        return extractJsonString(afterParts, "text");
    }

    static String truncate(String s, int max) {
        if (s == null) return "<null>";
        s = s.replace("\n", " ").replace("\r", "");
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
