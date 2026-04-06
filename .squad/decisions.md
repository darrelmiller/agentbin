# Squad Decisions

## Active Decisions

### Post-Deployment Smoke Testing (2026-03-21)
**Status:** Implemented | **Author:** Dashboard  

- Smoke test script at `tests/smoke-test.py` verifies all hosted agent endpoints
- Uses stdlib only (no pip install needed) — consistent with run-all.py patterns
- CI workflow at `.github/workflows/smoke-test.yml` supports:
  - `workflow_dispatch` for manual runs
  - `workflow_call` for chaining to future deploy workflows
  - Daily cron (8 AM UTC) as a health heartbeat
- Base URL parameterized (default: Azure Container Apps URL)
- **Endpoints tested:** /health, root catalog, /echo agent card, /spec03 v0.3 agent card

### Spec03 404 is a Deployment Gap (2026-03-21)
**Status:** Identified | **Author:** Legacy  

- Root cause: Deployed container predates spec03 addition — deployment is behind source code
- Source code is correct and works locally (`Program.cs` has proper route)
- **Fix:** Rebuild and redeploy Docker container from `origin/main`
- Impact: v0.3 interop tests and A2A Editor discovery currently unavailable
- No code changes needed — pure operational fix

### User Directive: Smoke Test After Every Publish (2026-03-21)
**Status:** Captured | **By:** Darrel (via Copilot)

- Context: spec03 agent broke in production without being caught by automated checks
- Directive: "We should be smoke testing agents after every publish"
- Implementation: See Post-Deployment Smoke Testing decision above

### Deployment Ownership: Spec Agent (2026-03-21)
**Status:** Implemented | **Author:** Darrel (via Copilot)

- Deployment to Azure Container Apps is owned by Spec agent
- Deploy commands: `az acr build --registry agentbinacr --image agentbin:latest .` then `az containerapp update -n agentbin -g agentbin-rg`
- Azure subscription: "Visual Studio Enterprise" — must be selected via `az account set`
- Process documented in Spec charter (`.squad/agents/v1-agents/charter.md`)
- Post-deployment: run smoke tests via `python tests/smoke-test.py`
- Cost: ~$5-6/month (ACR Basic + scale-to-zero Container App)
- Ensures deployment is repeatable and not ad-hoc

### JSON-RPC Transport Compatibility in @a2a-js/sdk (2026-03-22)
**Status:** Resolved | **Author:** TypeScript  

- `JsonRpcTransport` is still exported from `@a2a-js/sdk/client` (earlier audit was incorrect)
- However, it sends v0.3 method names (`message/send`) and doesn't call `fromJSON` on responses
- **Solution:** Created `v1_compat.mjs` compatibility layer with:
  - `V1JsonRpcTransport` — implements Transport interface with correct V1.0 method names and proto deserialization
  - `createV1RestFetch()` — fetch wrapper fixing `content↔parts` field naming for REST transport
  - State normalization: `TASK_STATE_CANCELED` (server) → `TASK_STATE_CANCELLED` (SDK)
  - Agent card capability normalization: `supportsStreaming` → `streaming`
- **Test results:** 49/58 pass (was 13/58 before changes)
- **Remaining 9 failures:** Server limitations (no history, no REST subscribe, sync return-immediately), SDK limitations (no listTasks, REST cancel has no body)

### DotNet run-all.py Process Lifecycle Issue (2026-07-25)
**Status:** Proposed | **Author:** DotNet  

- `tests/run-all.py` line 89 invokes test client as `["dotnet", "run", "--"]`
- This re-hosts the process; when parent terminates/times out, kills dotnet but leaves test client orphaned or kills server
- **Correct pattern:** Build exe first with `dotnet build`, then execute `bin/Debug/net10.0/A2AClientTests.exe` directly
- Standalone runner at `tests/ClientTests/dotnet/run.py` implements this correctly
- **Proposal:** Either add build step and invoke exe, or have `run-all.py` delegate to standalone run.py
- **Impact:** Fixes process lifecycle issues on Windows; aligns with DotNet charter

### Python SDK 1.0.0a0 Not on PyPI (2026-03-22)
**Status:** Informational | **Author:** Python  

- Test client depends on a2a-sdk version **1.0.0a0** (local build only, NOT on PyPI)
- Latest PyPI release is 0.3.25 — the 1.0.0a0 pre-release is not published
- Installed package was built from local repo at `D:\github\a2aproject\a2a-python` and installed as wheel
- **CI/CD impact:** Fresh environments (containers, GitHub Actions) cannot resolve this version from PyPI
- **Decision:** Keep current local build as intended; this note ensures team awareness
- **Upgrade path:** When 1.0.0 lands on PyPI, update `requirements.txt` to pin exact stable version

### Java SDK Version Gap: Alpha3 vs Beta1-SNAPSHOT (2026-03-21)
**Status:** Resolved | **Author:** Java  

- Test client pom.xml **upgraded** from groupId `io.github.a2asdk` version `1.0.0.Alpha3` to `org.a2aproject.sdk` version `1.0.0.Beta1-SNAPSHOT`
- Upstream SDK built locally from `D:\github\a2aproject\a2a-java` (requires `mvn clean install -DskipTests -Dinvoker.skip=true`)
- API changes adapted: CancelTaskParams, subscribeToTask signature, TaskPushNotificationConfig
- Beta SDK behavioral change: TaskEvent fires at SUBMITTED state; consumer patterns updated
- **Remaining issues:** JSONRPC transport protobuf bug (upstream), agent card unmarshalling (upstream)
- **Test results:** 27/58 pass (REST tests mostly work; JSONRPC transport blocked by SDK bug)

### User Directive: Never Publish Local Build Results Without Approval (2026-03-22)
**Status:** Captured | **By:** Darrel Miller (via Copilot)

- **What:** Never publish (push to origin, deploy, or update public dashboard) test results from local builds without explicit user approval first
- **Why:** Local build results may use unpublished SDKs and could be misleading if shared publicly
- **Implementation:** Dashboard agent added `--publish` flag to `run-all.py` with per-client gating (default off for local builds)
- **Benefit:** Maintains audit trail; prevents accidental publication of incomplete results

### REST Transport Requires Unpublished Preview2 Packages (2026-03-22)
**Status:** Confirmed | **Author:** DotNet

- The published `A2A 1.0.0-preview` and `A2A.AspNetCore 1.0.0-preview` NuGet packages do **not** include REST/HTTP+JSON support
  - **Client:** `A2AHttpJsonClient` class does not exist in published 1.0.0-preview
  - **Server:** `A2A.AspNetCore 1.0.0-preview` does not register REST routes (all return 404)
  - **JSON-RPC:** Works fine with published packages
- **Test results with published packages:** 29/58 pass (25/27 JSON-RPC, 0/27 REST, 4/4 v0.3)
- **With unpublished preview2:** 53/58 pass (25/27 JSON-RPC, 25/27 REST, 4/4 v0.3)
- **Team implication:** REST transport is a `1.0.0-preview2` feature; any team member needing REST must use local `nupkgs/` feed

### Java Known Failure Annotations: Client-Side Attribution Fix (2026-07-25)
**Status:** Implemented | **Author:** Dashboard

- All Java `KNOWN_FAILURES` annotations referencing `InvalidParamsError: Parameter 'id' may not be null` now correctly attribute it as a **client-side Java SDK issue**, not server rejection
- **Evidence:** Error string lives in `a2a-java/common/src/main/java/io/a2a/util/Assert.java`; fires in `Task` constructor during deserialization, not in .NET server
- **Impact:** ~25 annotations updated in `tests/run-all.py` (lines 255–329); dashboard accuracy improved; server exonerated from these failures
- **Team relevance:** 
  - Java agent: Reference client-side `Task` constructor when filing upstream issues against `a2a-java`
  - Spec agent: Server requires no fix for these failures

### Go SDK Upgrade: v2.0.0 → v2.0.1 (2026-07-25)
**Status:** Completed | **Author:** GoLang

- a2a-go/v2 SDK upgraded from v2.0.0 to v2.0.1 (already committed in `0b8285c`)
- **Key v2.0.1 changes:**
  - HTTP+JSON REST in v0.3 compat layer (`rest_client.go`, `rest_server.go` in `a2acompat/a2av0/`)
  - Concurrent cancellation fix for racing cancel operations
  - Agent executor post-execution callback API (additive)
  - Dependency bumps: grpc, protobuf, sync
- **No breaking API changes** — all additive or internal fixes
- **No test client modifications needed** — `main.go` compiles unmodified
- **Potential improvement:** v0.3 REST compat layer may fix 3 failing v0.3 tests
- **Team impact:** Go-specific, no cross-language implications

### Java SDK Upgrade: Alpha4 → Beta1-SNAPSHOT (2026-07-28)
**Status:** Completed | **Author:** Java

- Test client `pom.xml` upgraded from `1.0.0.Alpha4` to `1.0.0.Beta1-SNAPSHOT`
- Rebuilt upstream SDK from `D:\github\a2aproject\a2a-java` HEAD (10 commits past Alpha4)
- Test client compiles cleanly — no code changes required
- **Notable SDK changes:**
  - Structured error codes (`A2AErrorCodes` enum with `code()`, `grpcStatus()`, `httpCode()`)
  - `A2AError` API change: `getData()` → `getDetails()` (returns `Map<String, Object>`)
  - Stream interrupt fix: streams stay open on INPUT_REQUIRED, AUTH_REQUIRED states
  - `TaskState.isInterrupted()` method added
  - Agent card caching headers (server-side)
- **Null-ID bug:** Still present in Beta1-SNAPSHOT (architectural issue in protobuf→MapStruct→Task constructor pipeline)
- **Team impact:** Java-only; no action needed from other agents

### Subscribe-After-Stream-Disconnect Test Added (2026-03-26)
**Status:** Implemented | **Author:** DotNet

Added test #27 `subscribe-after-stream-disconnect` for both JSON-RPC and REST bindings to cover upstream issue `a2aproject/a2a-dotnet#340`.

- Issue #340: `SubscribeToTaskAsync` hangs indefinitely when reconnecting to an in-progress streaming task
- Existing `subscribe-to-task` tests only subscribe after non-blocking `SendMessageAsync` — missing "stream → disconnect → resubscribe" pattern
- **Test design:**
  - Uses `long-running` skill (~10s runtime) to ensure task remains in-progress during resubscribe
  - Phase 1: `SendStreamingMessageAsync` → capture taskId → disconnect
  - Phase 2: `SubscribeToTaskAsync` with 30s timeout → PASS if terminal state, FAIL if timeout
  - Timeout reports: "timeout — SubscribeToTaskAsync hung (a2a-dotnet#340)"
  - **No workarounds:** Test failures ARE the diagnostic signal
- **Dashboard impact:** Test IDs `jsonrpc/subscribe-after-stream-disconnect` and `rest/subscribe-after-stream-disconnect` — total tests: 58 → 60
- **Spec agent:** No server changes needed — long-running skill already supports this pattern
- **Other clients:** Consider equivalent tests for your SDKs

### Root /.well-known/agent-card.json Restored (2026-03-26)
**Status:** Implemented | **Author:** Spec

The domain-root `/.well-known/agent-card.json` endpoint is restored, returning the Spec agent's card.

- **Context:** Earlier removal broke JS, Rust, and other SDKs that discover agents via domain-root `.well-known`
- **Rationale:**
  - Root-level `.well-known` is a valid A2A discovery pattern, not a workaround
  - Spec agent is the primary agent; logical default discovery target
  - Echo and v0.3 agents remain discoverable at sub-paths (`/echo/`, `/spec03/`)
  - Card URLs point to `/spec/` endpoints — no routing ambiguity
- **Impact:** JS, Rust clients (and any SDK using domain-root discovery) can connect again; smoke test validation resumed

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction

### Rebuild preview2 nupkgs from a2a-dotnet main (2026-03-26)
**Status:** Completed | **Author:** Spec

- Upstream `a2a-dotnet` PR#335 merged into main — 13 new commits past previous HEAD `2a7d7b3`
- Major additions: `A2AHttpJsonClient` (REST client), `A2AClientFactory`, `A2AClientOptions`, `A2AErrorResponse`, `ProtocolBindingNames`
- Rebuilt `A2A.1.0.0-preview2.nupkg` (330KB) and `A2A.AspNetCore.1.0.0-preview2.nupkg` (111KB)
- Removed stale alpha packages from `agentbin/nupkgs/`
- Version remains 1.0.0-preview2 (no version bump in `src/Directory.Build.props`)
- AgentBin.csproj already references 1.0.0-preview2 — no csproj change needed
- Build verified: `dotnet restore` + `dotnet build` succeeded cleanly
- No breaking API changes for AgentBin
- **Committed:** c0eeef9

### DotNet REST Upgrade to preview2 (2026-03-26)
**Status:** Completed | **Author:** DotNet

- Upgraded `.NET test client` from `A2A 1.0.0-preview` to `A2A 1.0.0-preview2` (local nupkgs feed)
- REST transport activated: `A2AClientTests.csproj` version bump + REST client initialization replaced with real `A2AHttpJsonClient` calls
- Implementation: `A2ACardResolver.GetAgentCardAsync()` → `A2AClientFactory.Create(card, httpClient, options)` with `PreferredBindings = [ProtocolBindingNames.HttpJson]`
- No test logic changes — all 27 REST test code already existed, just needed real client
- **Score improvement:** 30/58 → 53/58 (+23 tests passing)
  - REST: 0/27 → 25/27
  - JSON-RPC: 25/27 (stable)
  - v0.3: 3/4 (preview2 SDK requires `supportedInterfaces` in AgentCard)
- 5 remaining failures are all server-side: `Blocking=false` not implemented, `subscribe-to-task` streaming timeout, SSE error handling, v0.3 agent card schema
- **Committed:** 82c0b8e

### Dashboard Regeneration After .NET Upgrade (2026-03-26)
**Status:** Completed | **Author:** Dashboard

- Re-ran full test suite after Spec rebuilt nupkgs and DotNet upgraded test client
- .NET score improvement cascaded: 30/58 → 53/58
- **Final baseline scores:**
  - .NET 53/58 (was 29/58 with published packages, 30/58 with preview2 wait)
  - Go 51/58 (stable)
  - Python 51/58 (stable)
  - Java 27/58 (stable)
  - JS 49/58 (stable)
- Removed blanket REST annotation for .NET
- Added 2 specific known failures: `spec-return-immediately` (server), `error-subscribe-not-found` (server)
- Updated v0.3 annotation: `spec03-agent-card` now marked as preview2 SDK requirement
- Dashboard published to docs/dashboard.html for GitHub Pages
- **Committed:** 54e139a

### Multi-Server Dashboard: SDK Updates + Cross-Server Testing (2026-04-06)
**Status:** Completed | **Author:** Dashboard

- All A2A SDK dependencies updated across all clients
- Full test matrix executed: 7 clients × 5 servers = 35 test runs
- **Server Maturity by Client Coverage:**
  - .NET: 56/62 (Production)
  - Go: 54/60 (Production)
  - Python: 55/60 (Production)
  - Java: 15/62 (Early)
  - Rust: 12/60 (Early)
- **Critical Finding:** Go v2.1.0 client shows anomaly — 4/60 vs .NET server but 53/60 vs Go server
  - Likely agent card discovery regression in SDK v2.1.0
  - Needs investigation: cross-server compatibility issue
- **Base URL Convention:** Must use `http://localhost:PORT` without `/spec` suffix; clients derive agent paths
- **Test Count:** .NET 58→62, others 58→60 (subscribe-after-stream-disconnect tests added)
- **Team Impact:** Java/Rust servers have significant feature gaps; Go client cross-server compat needs investigation
- **Dashboards Published:** 5 per-server dashboards to docs/ for GitHub Pages
- **Committed:** 214b4a9, 2d9ce14

### MapA2A No Longer Registers .well-known Routes (2026-03-28)
**Status:** Resolved | **Author:** Spec

Upstream PR#339 removed `.well-known/agent-card.json` route registration from `MapA2A()`. This is a **breaking change** for any agent relying on the framework to serve discovery endpoints.

- **Impact:** `/spec/.well-known/agent-card.json` went 404 on first deploy
- **Fix:** Added explicit `app.MapGet("/spec/.well-known/agent-card.json", ...)` — same pattern as echo and spec03
- **Lesson:** All three agents (spec, echo, spec03) now use explicit manual `.well-known` routes — we no longer depend on `MapA2A` for discovery
- **Team impact:** If any new agents are added, they MUST register their own `.well-known` endpoint manually
