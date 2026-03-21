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

### JSON-RPC Transport Removal in @a2a-js/sdk (2026-03-22)
**Status:** Needs Discussion | **Author:** TypeScript  

- Latest commit `c29f4f8` in a2a-js repo (epic/1.0_breaking_changes) removes `JsonRpcTransport` from client exports
- Test client imports `JsonRpcTransport` at lines 23 and 92 of `test_js_client.mjs`
- **Current state:** Works because node_modules was installed before removal; running `npm install` now will break JSON-RPC tests
- Also: Commit `a886b1a` switches codebase to proto-based types (may require additional import changes)
- **Impact:** All `jsonrpc/*` test IDs will fail; only `rest/*` and `v0.3/*` tests will survive
- **Options:** (1) Adapt tests to REST-only, (2) Pin SDK to pre-removal commit, (3) Wait for stabilization
- **Recommendation:** Option 1 — adapt tests to match SDK's intentional direction

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
**Status:** Identified | **Author:** Java  

- Test client pom.xml references groupId `io.github.a2asdk` version `1.0.0.Alpha3` (Maven Central artifacts)
- Upstream SDK at `D:\github\a2aproject\a2a-java` has moved to groupId `org.a2aproject.sdk` version `1.0.0.Beta1-SNAPSHOT`
- **Upstream change:** SDK underwent **groupId rename** (`io.github.a2asdk` → `org.a2aproject.sdk`)
- **Version gap:** Current pom.xml is 2 versions behind (Alpha3 → Alpha4-SNAPSHOT → Beta1-SNAPSHOT)
- **Known issue:** Alpha3 has protobuf deserialization issues (Task.id null in JSONRPC tests)
- **Options:** (1) Stay on Alpha3 (stable but stale), (2) Switch to Beta1-SNAPSHOT (requires local build + groupId change), (3) Wait for Maven Central publish
- **Impact:** Newer SDK versions may fix protobuf issues; no action taken per charter

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
