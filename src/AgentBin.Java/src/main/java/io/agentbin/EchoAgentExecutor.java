package io.agentbin;

import io.a2a.server.agentexecution.AgentExecutor;
import io.a2a.server.agentexecution.RequestContext;
import io.a2a.server.tasks.AgentEmitter;
import io.a2a.spec.A2AError;
import io.a2a.spec.TextPart;
import io.a2a.spec.UnsupportedOperationError;

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
