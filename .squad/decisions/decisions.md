# Team Decisions

## DotNet REST Binding Support Enabled

**Status:** Implemented | **Author:** DotNet  
**Date:** 2026-03-22

### Decision

Upgraded A2A SDK from `1.0.0-preview` to `1.0.0-preview2` (built from `support-rest` branch of `a2a-dotnet`). This enables real HTTP+JSON REST protocol binding tests using the new `A2AHttpJsonClient` class.

### Impact

- **Test coverage:** REST tests went from 0/27 (stub) to 25/27 (real SDK calls)
- **Total:** 53/58 pass (was 29/58)
- **Package version:** Both `A2A` and `A2A.AspNetCore` now at `1.0.0-preview2`
- **NuGet config:** Root `nuget.config` and test client `nuget.config` now include `./nupkgs` as a local feed source
- **Server:** Rebuilt with new SDK (no code changes needed — `MapHttpA2A` was already wired up)

### Known Issues (Server-Side)

- `spec-return-immediately` fails on both bindings — `Blocking=false` not implemented server-side
- `subscribe-to-task` fails on both bindings — server streaming bug
- `error-subscribe-not-found` (REST only) — server returns empty SSE stream instead of 404 error

### When This Branch Is Merged to Main

The `support-rest` branch of `a2a-dotnet` is not yet merged. When it is:
1. Published NuGet package will include REST support
2. Can switch from local feed back to nuget.org
3. Version will likely change — update `.csproj` references accordingly

## .NET REST Tests via A2AClientFactory

**Status:** Implemented | **Author:** DotNet  
**Date:** 2026-03-25

### Context

The .NET test client had 27 REST tests stubbed as "sdk-does-not-support" because `A2AHttpJsonClient` only exists in `A2A 1.0.0-preview2` (local nupkgs, not NuGet.org). The `darrelmiller/issue-331-version-negotiation` branch of a2a-dotnet provides `A2AClientFactory` to create binding-specific clients.

### Decision

1. **Use `A2AClientFactory.Create(agentCard, httpClient, options)` (sync overload)** to create REST clients — NOT `CreateAsync` which has a JSON parsing bug in preview2.
2. **Resolve agent cards with `A2ACardResolver`** first, then pass the `AgentCard` to the factory. This sidesteps the factory's internal card deserialization issue.
3. **Keep JSON-RPC tests using direct `new A2AClient(...)`** — no need to change what works.
4. **REST test logic mirrors JSON-RPC exactly** — both go through `IA2AClient` interface.

### Consequences

- REST test score: 0/27 → 25/27 (total: 29/58 → 54/58)
- Depends on local `A2A 1.0.0-preview2` nupkgs (not published to NuGet.org)
- When a fixed preview2 is published, the workaround can be simplified to use `CreateAsync` directly
- The `A2AClientFactory.CreateAsync` bug should be reported upstream

## Dockerfile Fix: Restore `COPY nupkgs/` for Preview2 Packages

**Status:** Confirmed Necessary | **Author:** Spec  
**Date:** 2026-03-25

### Summary

The uncommitted Dockerfile change adding `COPY nupkgs/ nupkgs/` before `dotnet restore` is **required and correct**.

### Root Cause

- Commit 893eb2a (Mar 22) upgraded A2A packages from `1.0.0-preview` (on nuget.org) to `1.0.0-preview2` (local-only, from support-rest branch)
- That commit updated `nuget.config` to re-add the `./nupkgs` local feed and updated `AgentBin.csproj` to reference `1.0.0-preview2`
- However, it **did not** update the Dockerfile to copy `nupkgs/` into the Docker build context
- The Dockerfile has been broken for ACR builds since that commit, but no deploy was attempted after the preview2 upgrade, so the bug was latent

### Evidence

- `nuget.config` (committed at HEAD): references `./nupkgs` as a package source
- `AgentBin.csproj` (committed at HEAD): references `A2A 1.0.0-preview2` and `A2A.AspNetCore 1.0.0-preview2`
- `nupkgs/` directory: contains `A2A.1.0.0-preview2.nupkg` and `A2A.AspNetCore.1.0.0-preview2.nupkg`
- `1.0.0-preview2` is NOT published on nuget.org — it comes from the support-rest branch of the A2A .NET SDK
- Without `COPY nupkgs/ nupkgs/`, `dotnet restore` would fail inside Docker

### Decision

Accept the Dockerfile change. It restores a line that was correctly present in the initial commit (aef5b95), was correctly removed when switching to nuget.org packages (5ff4466), and must be re-added now that we depend on local preview2 packages again (893eb2a).

### Future Note

When `1.0.0-preview2` (or later) is published to nuget.org, the local feed and this Dockerfile line can be removed again.

## Deployment Results: preview2 Cloud Build Fix

**Status:** Completed | **Author:** Spec  
**Date:** 2026-03-25

### Summary

Deployed agentbin with the Dockerfile fix (`COPY nupkgs/ nupkgs/`) that enables preview2 packages in cloud builds. This is the first successful deployment since the preview2 upgrade (commit 893eb2a).

### What Changed

- Committed `ca2d27e`: adds `COPY nupkgs/ nupkgs/` to Dockerfile so `dotnet restore` can find the local preview2 NuGet packages during ACR cloud builds
- Previously broken since preview2 upgrade — the Dockerfile was never updated when preview2 switched to local-only packages

### Deployment Verification

- **Health:** ✅ `/health` returns `Healthy`
- **Spec agent card:** ✅ `/spec` — v1.0 with JSONRPC + HTTP+JSON bindings
- **Echo agent card:** ✅ `/echo` — v1.0 with JSONRPC + HTTP+JSON bindings
- **Spec03 agent card:** ✅ `/spec03` — v0.3 compat, protocolVersion 0.3.0
- **REST transport:** ✅ Now available in production (enabled by preview2)

### Smoke Test Results

- **9/10 checks pass**
- **1 expected failure:** `GET /.well-known/agent-card.json` returns 404 — this root catalog endpoint was removed in commit `39cad22` as non-standard

### Team Action Needed

- `tests/smoke-test.py` still tests `/.well-known/agent-card.json` at root, which no longer exists. The test should be updated to either remove this check or replace it with the correct v1.0 discovery endpoints (`/spec`, `/echo`, `/spec03`).
