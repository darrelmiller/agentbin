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
