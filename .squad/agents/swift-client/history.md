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
