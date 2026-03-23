# Swift — History

## Core Context

- **Project:** agentbin — A2A v1.0 cross-language interoperability test bed
- **Stack:** C# / .NET 10 (server), Go / Python / Java / TypeScript / Rust / Swift (clients), Azure Container Apps
- **User:** Darrel Miller
- **SDK:** `A2AClient` from https://github.com/tolgaki/a2a-client-swift (Swift Package Manager)
- **Server:** https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io
- **Test agents:** echo (JSONRPC + REST), spec03 (v0.3 compat)
- **Test matrix:** 58 scenarios covering sendMessage, streaming, cancel, get-task, push notifications, v0.3 compat
- **Dashboard:** https://darrelmiller.github.io/agentbin/dashboard.html
- **Created:** 2026-03-22

## Learnings

- Agent joined the team on 2026-03-22. Swift client needs to be built from scratch.
- Other clients (Go, Python, JS) at 49-51/58 tests passing — use their patterns as reference.
- Each client has a standalone `run.py` in its directory that builds, runs, and produces results.json.
- `tests/run-all.py` delegates to per-client `run.py` scripts.
- The Swift SDK supports BOTH JSON-RPC and HTTP/REST transports — configure via `A2AClientConfiguration.transportBinding`.
- The Swift SDK has ALL 11 A2A operations including cancel, listTasks, subscribeToTask, push notification CRUD.
- Swift 6.0+ required. Check platform availability (macOS/Linux — Windows support is limited).
- **2026-07-18 — SDK v1.0.5 → v1.0.6 update & protocol alignment work (10/58 → 34/58)**
  - Updated Package.resolved to v1.0.6 (commit 375eda5c). Key fix: JSON-RPC `id` accepts both Int and String.
  - run.py reworked: `get_swift_env()` returns `(env, swift_exe)` tuple — Python on Windows doesn't search custom env PATH for executables.
  - Fixed PATH casing: vcvarsall.bat outputs `Path` (mixed case), creating `PATH` alongside it causes undefined behavior.
  - **Protocol patches (v0.3 SDK → v1.0 server)** — 8 categories applied via `patch_upstream_sdk()` in run.py:
    1. FoundationNetworking import (non-Apple only)
    2. URLSession.bytes(for:) → data(for:) fallback (non-Apple)
    3. JSON-RPC method names: `message/send` → `SendMessage` (11 replacements)
    4. MessageRole enum: `user` → `ROLE_USER`, `agent` → `ROLE_AGENT`
    4b. TaskState enum: `completed` → `TASK_STATE_COMPLETED` etc. (9 states). Note: `cancelled` → `TASK_STATE_CANCELED` (single L — proto convention)
    5. Remove v0.3 `kind` discriminator from Part/Message encoding
    6. Streaming event decoder: adds `StreamResponse`-based fallback for v1.0 keyed format (`{"result":{"task":..}}`)
    7. getTask: include task ID in queryItems so JSON-RPC params contains `{"id": "..."}` 
    8. fetchAgentCard: handle JSON arrays from root well-known endpoint (returns `[AgentCard, ...]`)
  - **Final results: 34/58 passing** (JSON-RPC: 23/27, REST: 7/27, v0.3: 4/4)
  - Remaining 24 failures breakdown:
    - REST 404 (19): Server needs preview2 NuGet packages for REST endpoints — not an SDK issue
    - Cancel race (2): `spec-task-cancel`, `spec-cancel-with-metadata` — task completes before cancel arrives
    - returnImmediately (1): Server ignores the flag (takes ~10s)
    - subscribe-to-task (1): Server returns "internal error during streaming"
    - rest/spec-get-task (1): Skipped, depends on REST lifecycle test
  - Key learning: a2a-client-swift v1.0.6 still speaks v0.3 wire format. All v1.0 protocol adaptation done via run.py patches.
