# Spec — History

## 2026-03-21 — Initial onboarding

- Server hosts 3 agents: /spec (SpecAgent), /echo (EchoAgent), /spec03 (v0.3 compat)
- Uses A2A NuGet 1.0.0-preview packages from local nupkgs/ folder
- BASE_URL auto-detection fixed: checks builder.Configuration["urls"] and ASPNETCORE_URLS
- Agent cards serialize with v0.3-compatible shape despite using v1.0 SupportedInterfaces
- return-immediately (Blocking=false) not implemented on server
- subscribe-to-task has "internal error during streaming" bug
- Deployed to Azure Container Apps

## Learnings

### 2026-03-21: Deployment ownership established
- Deployment to Azure Container Apps is now my responsibility
- ACR: agentbinacr, Resource Group: agentbin-rg, Subscription: Visual Studio Enterprise
- Deploy: `az acr build` then `az containerapp update`
- Post-deploy: run smoke tests (`python tests/smoke-test.py`)
- Cost: ~$5-6/month (ACR Basic + scale-to-zero Container App)

### 2026-07-25: Dockerfile nupkgs/ investigation
- Commit 5ff4466 (Mar 16) switched from local alpha to official 1.0.0-preview on nuget.org. Correctly removed `COPY nupkgs/ nupkgs/` from Dockerfile and the local feed from nuget.config. Deploys worked fine because preview packages were on nuget.org.
- Commit 893eb2a (Mar 22) upgraded to 1.0.0-preview2 (local-only, from support-rest branch). Added preview2 .nupkg files, re-added `./nupkgs` local feed to nuget.config, updated csproj to reference 1.0.0-preview2 — **but did NOT update the Dockerfile**.
- This means the Dockerfile has been broken for Docker builds since 893eb2a. `dotnet restore` would fail because nuget.config references `./nupkgs` which doesn't exist in the container (not copied), and preview2 is not on nuget.org.
- The uncommitted `COPY nupkgs/ nupkgs/` addition is **necessary and correct** — it fixes a latent bug from the preview2 upgrade.
- Previous successful deploys were all before the preview2 upgrade, which is why the broken Dockerfile was never caught.

### 2026-07-25: Successful deployment with preview2 Dockerfile fix
- Committed `ca2d27e`: `fix: add COPY nupkgs/ to Dockerfile for preview2 cloud builds`
- ACR cloud build succeeded — `dotnet restore` resolved preview2 packages from local `nupkgs/` feed inside the container
- Container app updated; health endpoint returned `Healthy` within 30s
- All 3 agent cards live: `/spec` (v1.0 JSONRPC+REST), `/echo` (v1.0 JSONRPC+REST), `/spec03` (v0.3 compat)
- Smoke test: **9/10 checks pass**. The 1 failure is `/.well-known/agent-card.json` at root — intentionally removed in commit `39cad22` as non-standard. Smoke test script needs updating to reflect this.
- REST transport now works in production for the first time (preview2 packages enable HTTP+JSON binding)

### 2026-03-26: Rebuilt preview2 nupkgs from upstream main (PR#335 merged)
- Upstream `a2a-dotnet` main updated from `2a7d7b3` to `2376b83` (13 new commits)
- Major additions: `A2AHttpJsonClient` (REST client), `A2AClientFactory`, `A2AClientOptions`, `A2AErrorResponse`, `ProtocolBindingNames` — plus many model cleanups and dep bumps
- Version remains `1.0.0-preview2` (no version bump in `src/Directory.Build.props`)
- AgentBin.csproj already references `1.0.0-preview2` — no csproj change needed
- Old alpha nupkgs removed (`A2A.1.0.0-alpha.nupkg`, `A2A.AspNetCore.1.0.0-alpha.nupkg`)
- New packages: `A2A.1.0.0-preview2.nupkg` (330KB, was 319KB) and `A2A.AspNetCore.1.0.0-preview2.nupkg` (111KB, was 111KB)
- Must clear NuGet global cache (`~/.nuget/packages/a2a/1.0.0-preview2`) before restore to pick up new content
- `dotnet restore` + `dotnet build` succeeded cleanly — no breaking API changes for AgentBin
- **Committed (2026-03-26):** c0eeef9 — nupkg rebuild approved and committed

## Cross-Agent Updates (2026-03-26)

### DotNet Test Client REST Activation
- Spec's nupkg rebuild enabled REST transport in preview2 packages
- DotNet agent upgraded test client to 1.0.0-preview2 and wired real `A2AHttpJsonClient`
- .NET score jumped 30→53/58, REST went 0/27→25/27
- This validates that server REST endpoints work correctly with preview2

### Dashboard Regeneration
- Dashboard re-ran full suite after DotNet upgrade
- Final baseline established: .NET 53/58, Go 51/58, Python 51/58, Java 27/58, JS 49/58
- All agents' results updated in dashboard and published to GitHub Pages

### 2026-03-26: Deployment — preview2 nupkg rebuild + .NET REST + dashboard
- **Trigger:** Nupkgs rebuilt from upstream PR#335, .NET test client upgraded (53/58), dashboard regenerated
- ACR cloud build: `az acr build --registry agentbinacr --image agentbin:latest .` — succeeded (Run ID: cag, 48s)
- Image digest: `sha256:1efc5791629fabd105566644f4cf4d6ac8a0c85037d3dc6c9ff3d1a9a1f48361`
- Container app updated: `az containerapp update -n agentbin -g agentbin-rg`
- **Verification:**
  - `/health` → `{"status":"Healthy"}` ✅
  - `/spec/.well-known/agent-card.json` → v1.0 JSONRPC+HTTP+JSON ✅
  - `/echo/.well-known/agent-card.json` → Echo Agent v1.0.0 ✅
  - `/spec03/.well-known/agent-card.json` → v0.3 compat agent ✅
- All 3 agents live with REST transport enabled in production

### 2026-07-28: Restored root /.well-known/agent-card.json endpoint
- Commit 39cad22 removed the domain-root `/.well-known/agent-card.json` as "non-standard"
- This broke JS, Rust, and other SDKs that hardcode agent discovery at the domain root
- Root `.well-known` IS a valid A2A pattern — many SDKs try it before trying sub-paths
- Fix: Added `app.MapGet("/.well-known/agent-card.json", ...)` returning the Spec agent's card
- Card URLs still point to `/spec/` paths — no ambiguity about which agent endpoints to use
- Caching middleware already covers any path ending in `/.well-known/agent-card.json` — no extra changes needed
- Build verified, committed as 9899743

### 2026-03-28: Rebuilt preview2 nupkgs from upstream PR#339 (ReturnImmediately)
- Upstream `a2a-dotnet` main updated from `2376b83` to `ce46aa0` (PR#339 merge)
- Key changes: `Blocking` renamed to `ReturnImmediately` with full server-side implementation, atomic `GetOrAdd` for CTS management
- **Breaking change discovered:** `MapA2A()` no longer registers `/.well-known/agent-card.json` routes — this was removed in PR#339
- `/spec/.well-known/agent-card.json` went 404 in first deploy; fixed by adding explicit `MapGet` route (echo/spec03 already had manual routes)
- Version remains `1.0.0-preview2` — no version bump in `src/Directory.Build.props`
- No csproj changes needed — AgentBin code doesn't reference `Blocking` or `ReturnImmediately` directly
- Two ACR builds: first caught the .well-known regression, second deployed the fix
- **Committed:** b88e8e4
- **Deployed:** ACR Run IDs caj + cak, image `sha256:7f8f3c55e66bcf0bb4d25d492f32dadf41f030b14e3e063c5d941f8d6e873187`
- All 5 production endpoints verified: /health, root .well-known, /spec, /echo, /spec03
- This should unblock `spec-return-immediately` test failures across all 7 clients
