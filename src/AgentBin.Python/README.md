# AgentBin Python Server

A2A v1.0 test server implementation in Python using the `a2a-sdk`.

## Features

- **SpecAgent** at `/spec` - 8 test skills for A2A compliance testing
- **EchoAgent** at `/echo` - Simple echo agent for connectivity testing
- Both JSON-RPC and REST interfaces
- Full streaming support
- CORS enabled

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python main.py
```

Environment variables:
- `PORT` - Server port (default: 5000)
- `BASE_URL` - Base URL for agent cards (default: `http://localhost:{PORT}`)

## Endpoints

- `http://localhost:5000/` - Server info
- `http://localhost:5000/health` - Health check
- `http://localhost:5000/.well-known/agent-card.json` - Default agent card (SpecAgent)
- `http://localhost:5000/spec` - SpecAgent (JSON-RPC POST, REST /v1/...)
- `http://localhost:5000/spec/.well-known/agent-card.json` - SpecAgent card
- `http://localhost:5000/echo` - EchoAgent (JSON-RPC POST, REST /v1/...)
- `http://localhost:5000/echo/.well-known/agent-card.json` - EchoAgent card

## SpecAgent Skills

1. **message-only** - Stateless message response (no task)
2. **task-lifecycle** - Full task: submitted → working → completed
3. **task-failure** - Task that fails with error message
4. **task-cancel** - Task that waits to be canceled
5. **multi-turn** - Multi-turn conversation (input-required)
6. **streaming** - Streamed response with multiple chunks
7. **long-running** - Long-running task with periodic updates
8. **data-types** - Mixed content: text, JSON, file (SVG), multi-part

Example usage:
```bash
curl -X POST http://localhost:5000/spec \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "task-lifecycle hello"}]
      }
    }
  }'
```

## Project Structure

- `main.py` - Server entry point
- `spec_agent.py` - SpecAgent executor (8 skills)
- `echo_agent.py` - EchoAgent executor
- `cards.py` - Agent card builders
- `requirements.txt` - Python dependencies
