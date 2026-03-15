# AgentBin — A2A v1.0 Test Bed Service

AgentBin is a publicly accessible, unauthenticated service that hosts A2A v1.0 agents designed as a **test bed for A2A client interactions**. Client implementers can validate their A2A integrations against live endpoints.

📊 **[Compatibility Dashboard](https://darrelmiller.github.io/agentbin/)** — Live cross-language SDK test results

## Agents

### Echo Agent (`/echo`)

A minimal message-only agent. Echoes back whatever you send. Use it to verify basic A2A connectivity.

- **Endpoint**: `POST /echo` (JSON-RPC)
- **Agent Card**: `GET /echo/.well-known/agent-card.json`
- **Capabilities**: No streaming, no push notifications

### Spec Agent (`/spec`)

A multi-skill agent that exercises all A2A v1.0 interaction patterns. Send a message starting with a skill keyword to trigger the corresponding test scenario.

- **Endpoint**: `POST /spec` (JSON-RPC)
- **Agent Card**: `GET /spec/.well-known/agent-card.json`
- **Capabilities**: Streaming enabled

| Skill | Keyword | What it tests |
|---|---|---|
| Message Only | `message-only` | Stateless message response (no task created) |
| Task Lifecycle | `task-lifecycle` | Full task: submitted → working → completed with artifact |
| Task Failure | `task-failure` | Task that transitions to failed state with error |
| Task Cancel | `task-cancel` | Task that waits in working state to be canceled |
| Multi-Turn | `multi-turn` | Input-required state, conversation continuation |
| Streaming | `streaming` | SSE streaming with multiple artifact chunks |
| Long Running | `long-running` | Periodic updates over ~10 seconds |
| Data Types | `data-types` | Mixed content: text, JSON, file (SVG), multi-part |

**Example** (JSON-RPC):
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "1",
  "params": {
    "message": {
      "messageId": "msg-001",
      "role": "ROLE_USER",
      "parts": [{ "text": "task-lifecycle hello world" }]
    }
  }
}
```

## Running Locally

```bash
cd src/AgentBin
dotnet run
```

The service starts on `http://localhost:8080` by default. Set the `BASE_URL` environment variable to override.

## Building the Docker Image

```bash
# Copy the local A2A NuGet packages into the build context
cp -r /path/to/a2a-dotnet/nupkgs ./nupkgs

# Build
docker build -t agentbin .

# Run
docker run -p 8080:8080 -e BASE_URL=http://localhost:8080 agentbin
```

## Deploying to Azure Container Apps

1. Create a resource group:
   ```bash
   az group create -n agentbin-rg -l eastus
   ```

2. Create an Azure Container Registry and push the image:
   ```bash
   az acr create -n agentbinacr -g agentbin-rg --sku Basic
   az acr login -n agentbinacr
   docker tag agentbin agentbinacr.azurecr.io/agentbin:latest
   docker push agentbinacr.azurecr.io/agentbin:latest
   ```

3. Update `infra/main.bicepparam` with your ACR and domain, then deploy:
   ```bash
   az deployment group create -g agentbin-rg -f infra/main.bicep -p infra/main.bicepparam
   ```

4. Update the `BASE_URL` environment variable to match the assigned FQDN.

## Health Check

```
GET /health
```

Returns `{ "Status": "Healthy", "Timestamp": "..." }`.
