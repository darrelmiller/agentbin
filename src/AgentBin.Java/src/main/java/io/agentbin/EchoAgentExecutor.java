package io.agentbin;

import org.a2aproject.sdk.server.agentexecution.AgentExecutor;
import org.a2aproject.sdk.server.agentexecution.RequestContext;
import org.a2aproject.sdk.server.tasks.AgentEmitter;
import org.a2aproject.sdk.spec.A2AError;
import org.a2aproject.sdk.spec.TextPart;
import org.a2aproject.sdk.spec.UnsupportedOperationError;

import java.util.List;

public class EchoAgentExecutor implements AgentExecutor {

    @Override
    public void execute(RequestContext context, AgentEmitter emitter) throws A2AError {
        String text = context.getUserInput("\n");
        emitter.sendMessage(List.of(new TextPart("Echo: " + text)));
    }

    @Override
    public void cancel(RequestContext context, AgentEmitter emitter) throws A2AError {
        throw new UnsupportedOperationError();
    }
}
