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

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
