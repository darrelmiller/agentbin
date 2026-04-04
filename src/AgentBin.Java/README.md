# AgentBin Java Server

Java A2A server implementation using the `a2a-java` SDK (version `1.0.0.Beta1-SNAPSHOT`).

## Overview

This server implements the **SpecAgent** test agent for A2A v1.0 compliance testing. It supports both JSON-RPC and REST (HTTP+JSON) transports using Quarkus.

## Features

- ✅ Full TCK routing support (15 test case prefixes)
- ✅ Keyword-based routing (complete, artifact, file, reject, input, stream, multi)
- ✅ Multi-turn conversation support (INPUT_REQUIRED state)
- ✅ Streaming artifacts with chunking
- ✅ Both JSON-RPC and REST transports
- ✅ Extended agent card support
- ✅ Port configuration via environment variable

## Architecture

- **Quarkus** — Application framework with CDI
- **a2a-java SDK** — A2A protocol implementation
  - `reference-jsonrpc` — JSON-RPC transport
  - `reference-rest` — REST (HTTP+JSON) transport
- **Single agent per application** — Java SDK architecture pattern

## Files

- `pom.xml` — Maven project configuration
- `src/main/resources/application.properties` — Quarkus configuration
- `src/main/java/io/agentbin/SpecAgentExecutor.java` — Agent business logic
- `src/main/java/io/agentbin/AgentExecutorProducer.java` — CDI executor producer
- `src/main/java/io/agentbin/AgentCardProducer.java` — CDI agent card producers
- `src/main/java/io/agentbin/ServerResource.java` — JAX-RS health/root endpoints

## Build

```bash
cd src/AgentBin.Java
mvn package -DskipTests
```

## Run

```bash
java -jar target/quarkus-app/quarkus-run.jar
```

Or with Quarkus dev mode:

```bash
mvn quarkus:dev
```

## Port Configuration

Default port: `5000`

Override via environment variable:
```bash
PORT=8080 java -jar target/quarkus-app/quarkus-run.jar
```

Or via property:
```bash
java -Dquarkus.http.port=8080 -jar target/quarkus-app/quarkus-run.jar
```

## Endpoints

- `GET /health` — Health check (returns "OK")
- `GET /` — Server info
- `GET /.well-known/agent-card.json` — Agent card (auto-registered by SDK)
- `POST /` — JSON-RPC endpoint
- `POST /v1/message/send` — REST endpoint
- `GET /v1/message/subscribe` — REST SSE subscribe endpoint

## Notes

- The Java SDK currently supports **one agent per Quarkus application**
- EchoAgent was not included due to this SDK constraint
- The SDK auto-registers routes for both transports based on classpath presence
- Extended agent card is produced but requires authentication to access
