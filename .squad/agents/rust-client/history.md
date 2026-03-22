# Rust — History

## Core Context

- **Project:** agentbin — A2A v1.0 cross-language interoperability test bed
- **Stack:** C# / .NET 10 (server), Go / Python / Java / TypeScript / Rust (clients), Azure Container Apps
- **User:** Darrel Miller
- **SDK:** `a2a-rs-client` v1.0.5 from crates.io (https://github.com/tolgaki/a2a-rs)
- **Server:** https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io
- **Test agents:** echo (JSONRPC + REST), spec03 (v0.3 compat)
- **Test matrix:** 58 scenarios covering sendMessage, streaming, cancel, get-task, push notifications, v0.3 compat
- **Dashboard:** https://darrelmiller.github.io/agentbin/dashboard.html
- **Created:** 2026-03-22

## Learnings

- Agent joined the team on 2026-03-22. Rust client needs to be built from scratch.
- Other clients (Go, Python, JS) at 49-51/58 tests passing — use their patterns as reference.
- Each client has a standalone `run.py` in its directory that builds, runs, and produces results.json.
- `tests/run-all.py` delegates to per-client `run.py` scripts.
- The a2a-rs SDK supports JSON-RPC transport via reqwest + tokio async.
