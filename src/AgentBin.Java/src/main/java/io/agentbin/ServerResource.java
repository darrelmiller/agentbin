package io.agentbin;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

@Path("/")
public class ServerResource {

    @GET
    @Path("/health")
    @Produces(MediaType.TEXT_PLAIN)
    public String health() {
        return "OK";
    }

    @GET
    @Produces(MediaType.TEXT_PLAIN)
    public String root() {
        return "AgentBin Java Server\nAgents: /spec, /echo\nHealth: /health\n";
    }
}
