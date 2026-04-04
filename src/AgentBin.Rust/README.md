# AgentBin Rust Server

A Rust implementation of the AgentBin A2A v1.0 server using the `a2a-rs` SDK.

## Overview

This server implements two A2A agents:

1. **SpecAgent** (`/spec`) — A spec compliance test agent with 8 skills
2. **EchoAgent** (`/echo`) — A simple echo agent

## Building

```bash
cargo build
cargo run
```

## Configuration

- **PORT**: Server port (default: 5000)
- **BASE_URL**: Base URL for agent cards (default: http://localhost:5000)

## Endpoints

- `GET /health` — Health check
- `GET /.well-known/agent-card.json` — Spec agent card
- `POST /spec/v1/rpc` — Spec agent JSON-RPC endpoint
- `GET /spec/.well-known/agent-card.json` — Spec agent card
- `POST /echo/v1/rpc` — Echo agent JSON-RPC endpoint
- `GET /echo/.well-known/agent-card.json` — Echo agent card

## SpecAgent Skills

The Spec Agent implements 8 skills to test A2A protocol features:

1. **message-only** — Returns a direct message without creating a task
2. **task-lifecycle** — Full task lifecycle: submitted → working → completed
3. **task-failure** — Simulates a task failure
4. **task-cancel** — Task that can be canceled (simplified in Rust)
5. **multi-turn** — Multi-turn conversation using input-required state
6. **streaming** — Streamed response (simplified in Rust, returns all chunks at once)
7. **long-running** — Long-running task with multiple steps (simplified in Rust)
8. **data-types** — Demonstrates various artifact content types

## Implementation Notes

The Rust SDK (`a2a-rs-server`) uses a synchronous handler pattern that differs from the Go SDK's streaming iterator approach. As a result:

- **Streaming and long-running tasks** return all content at once rather than streaming events over time
- **Task cancellation** returns a completed task immediately rather than waiting for a cancel request
- **Multi-turn conversations** work correctly using the task store

For full streaming/async behavior, use the Go or Python implementations which support the event-driven patterns.

## Dependencies

- `a2a-rs-server = "1.0.14"` — A2A server framework
- `a2a-rs-core = "1.0.14"` — A2A core types
- `axum = "0.7"` — Web framework
- `tokio` — Async runtime
- `tower-http` — CORS middleware

## Agent Cards

Both agents expose agent cards at `/.well-known/agent-card.json` containing:
- Agent metadata (name, description, version)
- Supported interfaces (JSON-RPC)
- Available skills with examples
- Default input/output modes

## License

This is a test/demo server for A2A protocol compliance testing.
