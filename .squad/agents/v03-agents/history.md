# Legacy — History

## 2026-03-21 — Initial onboarding

- v0.3 agent at /spec03 speaks only v0.3 protocol
- V03EndpointHandler.cs handles v0.3 JSON-RPC method name translation
- .NET client: 4/4 v0.3 tests pass
- Python client: 1/4 v0.3 tests pass (SDK sends v1.0 method names)
- Go client: v0.3 tests in 51/58 overall count
- Known issue: Python SDK doesn't negotiate down to v0.3 method names

## 2026-03-21 — Spec03 agent-card 404 investigation

### Root Cause
The Azure Container App is running a stale Docker container built from a commit
**before** `8c6337a` ("Add v0.3-only agent and backward compatibility tests").
The `/spec03` routes don't exist in the deployed container at all.

### Evidence
- Locally: ALL endpoints work — `/spec03/.well-known/agent-card.json` returns HTTP 200
  with correct v0.3 agent card (protocolVersion: "0.3.0")
- Deployed: ALL `/spec03` routes return HTTP 404 (both GET agent-card and POST JSON-RPC)
- Root agent card (`/.well-known/agent-card.json`) returns only 2 agents (spec + echo),
  not the expected 3 (spec + echo + spec03)
- `/spec` and `/echo` endpoints work correctly on deployed version
- Source code on `origin/main` has correct spec03 registration in Program.cs (lines 62-68)
- No automated CI/CD pipeline exists for container deployment
- `smoke-test.yml` exists locally but hasn't been pushed to GitHub

### Fix Required
**Redeploy the Docker container** from current `origin/main` (commit `bc64be6`).
No source code changes needed — the registration logic is correct.

### Prevention
Push `smoke-test.yml` to GitHub and activate daily runs to catch deployment gaps.

## Learnings

- The v0.3 agent is registered at `/spec03` with a separate `A2AServer` instance (not DI)
- `MapA2A(server, path)` only registers the POST JSON-RPC endpoint — it does NOT
  auto-register the agent card. Must use `MapGet` for the card endpoint separately.
- `MapA2A(path)` (DI overload) registers BOTH the POST endpoint and the agent card
- V03TranslationMiddleware correctly skips `/spec03` agent card (line 31: `!StartsWithSegments("/spec03")`)
- Key files: `src/AgentBin/Program.cs` (routing), `src/AgentBin/V03Compat/V03EndpointHandler.cs` (middleware),
  `src/AgentBin/Agents/SpecAgent.cs` (GetV03AgentCard method)
- Smoke test at `tests/smoke-test.py` already validates spec03 — just needs the workflow pushed
