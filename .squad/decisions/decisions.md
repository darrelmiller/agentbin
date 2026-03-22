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
