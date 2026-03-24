# Decision: .NET REST Tests via A2AClientFactory

**Date:** 2026-07-25  
**Author:** DotNet  
**Status:** Implemented

## Context

The .NET test client had 27 REST tests stubbed as "sdk-does-not-support" because `A2AHttpJsonClient` only exists in `A2A 1.0.0-preview2` (local nupkgs, not NuGet.org). The `darrelmiller/issue-331-version-negotiation` branch of a2a-dotnet provides `A2AClientFactory` to create binding-specific clients.

## Decision

1. **Use `A2AClientFactory.Create(agentCard, httpClient, options)` (sync overload)** to create REST clients — NOT `CreateAsync` which has a JSON parsing bug in preview2.
2. **Resolve agent cards with `A2ACardResolver`** first, then pass the `AgentCard` to the factory. This sidesteps the factory's internal card deserialization issue.
3. **Keep JSON-RPC tests using direct `new A2AClient(...)`** — no need to change what works.
4. **REST test logic mirrors JSON-RPC exactly** — both go through `IA2AClient` interface.

## Consequences

- REST test score: 0/27 → 25/27 (total: 29/58 → 54/58)
- Depends on local `A2A 1.0.0-preview2` nupkgs (not published to NuGet.org)
- When a fixed preview2 is published, the workaround can be simplified to use `CreateAsync` directly
- The `A2AClientFactory.CreateAsync` bug should be reported upstream
