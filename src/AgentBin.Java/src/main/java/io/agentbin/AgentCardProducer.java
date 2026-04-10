package io.agentbin;

import org.a2aproject.sdk.server.ExtendedAgentCard;
import org.a2aproject.sdk.server.PublicAgentCard;
import org.a2aproject.sdk.spec.*;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.inject.Produces;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

@ApplicationScoped
public class AgentCardProducer {

    @ConfigProperty(name = "quarkus.http.port", defaultValue = "5000")
    String port;

    @ConfigProperty(name = "agentbin.base-url", defaultValue = "")
    String configuredBaseUrl;

    private String getBaseUrl() {
        if (configuredBaseUrl != null && !configuredBaseUrl.isEmpty()) {
            return configuredBaseUrl;
        }
        return "http://localhost:" + port;
    }

    @Produces
    @PublicAgentCard
    public AgentCard specAgentCard() {
        String baseUrl = getBaseUrl();
        return AgentCard.builder()
                .name("AgentBin Spec Agent (Java)")
                .description("A2A v1.0 spec compliance test agent. Exercises all interaction patterns for client validation.")
                .version("1.0.0")
                .supportedInterfaces(List.of(
                        new AgentInterface(TransportProtocol.JSONRPC.asString(), baseUrl),
                        new AgentInterface(TransportProtocol.HTTP_JSON.asString(), baseUrl)
                ))
                .defaultInputModes(Collections.singletonList("text"))
                .defaultOutputModes(Collections.singletonList("text"))
                .capabilities(AgentCapabilities.builder()
                        .streaming(true)
                        .extendedAgentCard(true)
                        .build())
                .skills(specSkills())
                .build();
    }

    @Produces
    @ExtendedAgentCard
    public AgentCard extendedSpecAgentCard() {
        String baseUrl = getBaseUrl();
        List<AgentSkill> skills = new ArrayList<>(specSkills());
        skills.add(AgentSkill.builder()
                .id("admin-status")
                .name("Admin Status")
                .description("Returns server admin status (requires auth)")
                .tags(List.of("admin", "status"))
                .examples(List.of("admin-status"))
                .build());

        return AgentCard.builder()
                .name("AgentBin Spec Agent (Extended - Java)")
                .description("Extended agent card with additional skills (requires authentication).")
                .version("1.0.0")
                .supportedInterfaces(List.of(
                        new AgentInterface(TransportProtocol.JSONRPC.asString(), baseUrl),
                        new AgentInterface(TransportProtocol.HTTP_JSON.asString(), baseUrl)
                ))
                .defaultInputModes(Collections.singletonList("text"))
                .defaultOutputModes(Collections.singletonList("text"))
                .capabilities(AgentCapabilities.builder()
                        .streaming(true)
                        .extendedAgentCard(true)
                        .build())
                .skills(skills)
                .build();
    }

    private List<AgentSkill> specSkills() {
        return List.of(
                AgentSkill.builder()
                        .id("message-only")
                        .name("Message Only")
                        .description("Stateless message response (no task created)")
                        .tags(List.of("message", "stateless"))
                        .examples(List.of("message-only hello world"))
                        .build(),
                AgentSkill.builder()
                        .id("task-lifecycle")
                        .name("Task Lifecycle")
                        .description("Full task: submitted → working → completed")
                        .tags(List.of("task", "lifecycle"))
                        .examples(List.of("task-lifecycle hello world"))
                        .build(),
                AgentSkill.builder()
                        .id("task-failure")
                        .name("Task Failure")
                        .description("Task that fails with error message")
                        .tags(List.of("task", "failure"))
                        .examples(List.of("task-failure"))
                        .build(),
                AgentSkill.builder()
                        .id("task-cancel")
                        .name("Task Cancel")
                        .description("Task that waits to be canceled")
                        .tags(List.of("task", "cancel"))
                        .examples(List.of("task-cancel"))
                        .build(),
                AgentSkill.builder()
                        .id("multi-turn")
                        .name("Multi-Turn")
                        .description("Multi-turn conversation (input-required)")
                        .tags(List.of("multi-turn", "conversation"))
                        .examples(List.of("multi-turn start a conversation"))
                        .build(),
                AgentSkill.builder()
                        .id("streaming")
                        .name("Streaming")
                        .description("Streamed response with multiple chunks")
                        .tags(List.of("streaming", "sse"))
                        .examples(List.of("streaming"))
                        .build(),
                AgentSkill.builder()
                        .id("long-running")
                        .name("Long Running")
                        .description("Long-running task with periodic updates")
                        .tags(List.of("long-running", "polling"))
                        .examples(List.of("long-running"))
                        .build(),
                AgentSkill.builder()
                        .id("data-types")
                        .name("Data Types")
                        .description("Mixed content: text, JSON, file, multi-part")
                        .tags(List.of("data", "artifacts"))
                        .examples(List.of("data-types"))
                        .build()
        );
    }
}
