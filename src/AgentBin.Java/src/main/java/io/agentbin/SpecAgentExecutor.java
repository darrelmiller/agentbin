package io.agentbin;

import io.a2a.server.agentexecution.AgentExecutor;
import io.a2a.server.agentexecution.RequestContext;
import io.a2a.server.tasks.AgentEmitter;
import io.a2a.spec.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Base64;
import java.util.List;
import java.util.Map;

public class SpecAgentExecutor implements AgentExecutor {
    private static final Logger logger = LoggerFactory.getLogger(SpecAgentExecutor.class);

    @Override
    public void execute(RequestContext context, AgentEmitter emitter) throws A2AError {
        String messageId = context.getMessage() != null ? context.getMessage().messageId() : null;
        
        // TCK routing: if messageId starts with "tck-", extract prefix and route
        if (messageId != null && messageId.startsWith("tck-")) {
            routeTck(messageId, context, emitter);
            return;
        }

        // Multi-turn continuation
        Task existingTask = context.getTask();
        if (existingTask != null && existingTask.status().state() == TaskState.TASK_STATE_INPUT_REQUIRED) {
            handleMultiTurnContinuation(context, emitter);
            return;
        }

        // Keyword routing
        String text = context.getUserInput("\n");
        String keyword = extractKeyword(text);

        switch (keyword) {
            case "complete" -> handleComplete(emitter);
            case "artifact" -> handleArtifact(emitter);
            case "file" -> handleFile(emitter);
            case "reject" -> handleReject(emitter);
            case "input" -> handleInput(emitter);
            case "stream" -> handleStream(emitter);
            case "multi" -> handleMulti(context, emitter);
            default -> handleEcho(text, emitter);
        }
    }

    @Override
    public void cancel(RequestContext context, AgentEmitter emitter) throws A2AError {
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Task canceled by client request")))
                .build();
        emitter.cancel(msg);
    }

    private String extractKeyword(String text) {
        if (text == null || text.trim().isEmpty()) {
            return "";
        }
        String[] parts = text.trim().toLowerCase().split("\\s+", 2);
        return parts[0];
    }

    private void handleComplete(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        emitter.startWork();
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Task completed successfully")))
                .build();
        emitter.complete(msg);
    }

    private void handleArtifact(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Generated artifact content")),
                "result-artifact",
                "result.txt",
                null
        );
        emitter.complete();
    }

    private void handleFile(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        emitter.startWork();
        
        // Create a file part with bytes
        FileWithBytes fileContent = new FileWithBytes("text/plain", "output.txt", "Sample file content".getBytes());
        FilePart filePart = new FilePart(fileContent);
        
        emitter.addArtifact(
                List.of(filePart),
                "file-artifact",
                "File Artifact",
                null
        );
        emitter.complete();
    }

    private void handleReject(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Task rejected")))
                .build();
        emitter.reject(msg);
    }

    private void handleInput(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Please provide additional input")))
                .build();
        emitter.requiresInput(msg);
    }

    private void handleStream(AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        emitter.startWork();
        
        // Stream multiple chunks
        String[] chunks = {"Chunk 1...", "Chunk 2...", "Chunk 3..."};
        for (int i = 0; i < chunks.length; i++) {
            emitter.addArtifact(
                    List.of(new TextPart(chunks[i])),
                    "stream-artifact",
                    "Stream Result",
                    null,
                    i > 0,  // append
                    i == chunks.length - 1  // lastChunk
            );
        }
        emitter.complete();
    }

    private void handleMulti(RequestContext context, AgentEmitter emitter) {
        if (emitter.getTaskId() == null) {
            emitter.submit();
        }
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Received initial message: " + context.getUserInput("\n"))),
                "turn-1",
                "turn-1",
                null
        );
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Please send a follow-up message. Say 'done' to complete.")))
                .build();
        emitter.requiresInput(msg);
    }

    private void handleMultiTurnContinuation(RequestContext context, AgentEmitter emitter) {
        emitter.startWork();
        String text = context.getUserInput("\n");
        boolean isDone = text.toLowerCase().contains("done");
        
        if (isDone) {
            emitter.addArtifact(
                    List.of(new TextPart("Final message received: " + text)),
                    "final",
                    "final",
                    null
            );
            Message msg = Message.builder()
                    .role(Message.Role.ROLE_AGENT)
                    .parts(List.of(new TextPart("Conversation complete.")))
                    .build();
            emitter.complete(msg);
        } else {
            emitter.addArtifact(
                    List.of(new TextPart("Continuation received: " + text)),
                    "turn-" + System.currentTimeMillis(),
                    "turn-" + System.currentTimeMillis(),
                    null
            );
            Message msg = Message.builder()
                    .role(Message.Role.ROLE_AGENT)
                    .parts(List.of(new TextPart("Got it. Send another message, or say 'done' to complete.")))
                    .build();
            emitter.requiresInput(msg);
        }
    }

    private void handleEcho(String text, AgentEmitter emitter) {
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Echo: " + text)))
                .build();
        emitter.sendMessage(List.of(new TextPart("Echo: " + text)));
    }

    // TCK routing
    private void routeTck(String messageId, RequestContext context, AgentEmitter emitter) throws A2AError {
        String prefix = extractTckPrefix(messageId);
        
        switch (prefix) {
            case "complete-task" -> tckCompleteTask(emitter);
            case "artifact-text" -> tckArtifactText(emitter);
            case "artifact-file" -> tckArtifactFile(emitter);
            case "artifact-file-url" -> tckArtifactFileUrl(emitter);
            case "artifact-data" -> tckArtifactData(emitter);
            case "message-response" -> tckMessageResponse(emitter);
            case "input-required" -> tckInputRequired(emitter);
            case "reject-task" -> tckRejectTask(emitter);
            case "stream-001" -> tckStream001(emitter);
            case "stream-002" -> tckStream002(emitter);
            case "stream-003" -> tckStream003(emitter);
            case "stream-ordering-001" -> tckStreamOrdering001(emitter);
            case "stream-artifact-text" -> tckStreamArtifactText(emitter);
            case "stream-artifact-file" -> tckStreamArtifactFile(emitter);
            case "stream-artifact-chunked" -> tckStreamArtifactChunked(emitter);
            default -> handleEcho("Unknown TCK prefix: " + prefix, emitter);
        }
    }

    private String extractTckPrefix(String messageId) {
        // Strip "tck-" prefix
        String withoutPrefix = messageId.substring(4);
        // Strip last "-{hex}" segment
        int lastDash = withoutPrefix.lastIndexOf('-');
        if (lastDash > 0) {
            return withoutPrefix.substring(0, lastDash);
        }
        return withoutPrefix;
    }

    // TCK handlers
    private void tckCompleteTask(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Hello from TCK")))
                .build();
        emitter.complete(msg);
    }

    private void tckArtifactText(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Generated text content")),
                "text-artifact",
                "text-artifact",
                null
        );
        emitter.complete();
    }

    private void tckArtifactFile(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        FileWithBytes fileContent = new FileWithBytes("text/plain", "output.txt", "file content".getBytes());
        FilePart filePart = new FilePart(fileContent);
        emitter.addArtifact(
                List.of(filePart),
                "file-artifact",
                "file-artifact",
                null
        );
        emitter.complete();
    }

    private void tckArtifactFileUrl(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        FileWithUri fileContent = new FileWithUri("text/plain", "output.txt", "https://example.com/output.txt");
        FilePart filePart = new FilePart(fileContent);
        emitter.addArtifact(
                List.of(filePart),
                "file-url-artifact",
                "file-url-artifact",
                null
        );
        emitter.complete();
    }

    private void tckArtifactData(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        DataPart dataPart = new DataPart(Map.of("key", "value", "count", 42), null);
        emitter.addArtifact(
                List.of(dataPart),
                "data-artifact",
                "data-artifact",
                null
        );
        emitter.complete();
    }

    private void tckMessageResponse(AgentEmitter emitter) {
        emitter.sendMessage(List.of(new TextPart("Direct message response")));
    }

    private void tckInputRequired(AgentEmitter emitter) {
        emitter.submit();
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("Input required — send a follow-up message.")))
                .build();
        emitter.requiresInput(msg);
    }

    private void tckRejectTask(AgentEmitter emitter) {
        emitter.submit();
        Message msg = Message.builder()
                .role(Message.Role.ROLE_AGENT)
                .parts(List.of(new TextPart("rejected")))
                .build();
        emitter.fail(msg);
    }

    private void tckStream001(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Stream hello from TCK")),
                "stream-artifact",
                "stream-artifact",
                null
        );
        emitter.complete();
    }

    private void tckStream002(AgentEmitter emitter) {
        emitter.submit();
        emitter.complete();
    }

    private void tckStream003(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Stream task lifecycle")),
                "stream-artifact",
                "stream-artifact",
                null
        );
        emitter.complete();
    }

    private void tckStreamOrdering001(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Ordered output")),
                "stream-artifact",
                "stream-artifact",
                null
        );
        emitter.complete();
    }

    private void tckStreamArtifactText(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        emitter.addArtifact(
                List.of(new TextPart("Streamed text content")),
                "stream-text-artifact",
                "stream-text-artifact",
                null
        );
        emitter.complete();
    }

    private void tckStreamArtifactFile(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        FileWithBytes fileContent = new FileWithBytes("text/plain", "output.txt", "file content".getBytes());
        FilePart filePart = new FilePart(fileContent);
        emitter.addArtifact(
                List.of(filePart),
                "stream-file-artifact",
                "stream-file-artifact",
                null
        );
        emitter.complete();
    }

    private void tckStreamArtifactChunked(AgentEmitter emitter) {
        emitter.submit();
        emitter.startWork();
        
        // First chunk
        emitter.addArtifact(
                List.of(new TextPart("chunk-1 ")),
                "chunked-artifact",
                "Chunked Artifact",
                null,
                false,  // append
                false   // lastChunk
        );
        
        // Second chunk (append + lastChunk)
        emitter.addArtifact(
                List.of(new TextPart("chunk-2")),
                "chunked-artifact",
                "Chunked Artifact",
                null,
                true,   // append
                true    // lastChunk
        );
        
        emitter.complete();
    }
}
