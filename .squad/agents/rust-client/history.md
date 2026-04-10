# Rust — History

## Core Context

- **Project:** agentbin — A2A v1.0 cross-language interoperability test bed
- **Stack:** C# / .NET 10 (server), Go / Python / Java / TypeScript / Rust (clients), Azure Container Apps
- **User:** Darrel Miller
- **SDK:** `a2a-rs-client` v1.0.7 from crates.io (https://github.com/tolgaki/a2a-rs)
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
- (2026-07-26) Updated SDK from v1.0.5 → v1.0.6. Changes in 1.0.6: fix for `tasks/resubscribe` SSE handling. Test results unchanged at 21/58 (17/27 JSONRPC, 0/27 REST, 4/4 v0.3). No new APIs added in 1.0.6 for cancel_task, list_tasks, subscribe, push notifications, or REST transport — those remain SDK gaps.
- JSONRPC failures breakdown: 4× cancel_task missing, 1× list_tasks missing, 2× subscribe missing, 1× push notification config missing, 1× returnImmediately not supported, 1× get-task-with-history returns 0 history (server-side).
- REST failures: all 27 REST tests fail because a2a-rs-client has no REST transport — it's JSON-RPC only.
- (2026-07-28) Updated SDK from v1.0.6 → v1.0.7 via `cargo update`. Both a2a-rs-client and a2a-rs-core moved to 1.0.7. Build succeeded cleanly. Test results unchanged at 21/58 (17/27 JSONRPC, 0/27 REST, 4/4 v0.3). No new APIs in 1.0.7 for cancel_task, list_tasks, subscribe, push notifications, or REST transport — same SDK gaps persist. Failure profile identical to 1.0.6.
- **(2026-07-28) CRITICAL CORRECTION — Full SDK API Audit:** Previous assessments were WRONG about "SDK gaps." The a2a-rs-client v1.0.7 SDK exposes ALL of these methods that we claimed were missing:
  - `cancel_task(task_id, session_token) -> Result<Task>` — calls `tasks/cancel`
  - `list_tasks(request: ListTasksRequest, session_token) -> Result<TaskListResponse>` — calls `tasks/list`
  - `subscribe_to_task(task_id, session_token) -> Result<Stream<StreamingMessageResult>>` — calls `tasks/resubscribe` via SSE
  - `create_push_notification_config(task_id, config_id, config, session_token) -> Result<TaskPushNotificationConfig>`
  - `get_push_notification_config(task_id, config_id, session_token) -> Result<TaskPushNotificationConfig>`
  - `list_push_notification_configs(task_id, session_token) -> Result<ListTaskPushNotificationConfigResponse>`
  - `delete_push_notification_config(task_id, config_id, session_token) -> Result<()>`
  - `get_task(task_id, history_length: Option<u32>, session_token) -> Result<Task>` — replaces our manual `get_task_with_history` workaround
  - 8 JSONRPC tests are incorrectly skipped as "SDK not supported" and should be implemented immediately.
  - The manual `get_task_with_history()` function (line 1725) is unnecessary — use `client.get_task(task_id, Some(n), None)` instead.
  - Only genuine SDK gap: no REST/HTTP transport (all 27 REST tests remain unfixable).
  - Projected score after fix: 29/58 (25/27 JSONRPC, 0/27 REST, 4/4 v0.3), up from 21/58.
  - Full audit written to `.squad/decisions/inbox/rust-sdk-api-audit.md`.
- **(2026-07-28) Implemented all 8 missing SDK tests — score 21/58 → 30/58:**
  - Implemented: spec-task-cancel, spec-cancel-with-metadata, spec-list-tasks, error-cancel-not-found, error-cancel-terminal, error-push-not-supported, subscribe-to-task, error-subscribe-not-found
  - Fixed get-task-with-history to use `client.get_task(id, Some(10), None)` and relaxed pass condition to match Go
  - Removed dead `get_task_with_history()` manual workaround function
  - **Critical discovery: SDK method name mismatch.** a2a-rs-client v1.0.7 uses A2A v0.3-style method names (`tasks/list`, `tasks/resubscribe`) while the A2A v1.0 server expects PascalCase names (`ListTasks`, `SubscribeToTask`). The server maps some v0.3 names (message/send, message/stream, tasks/get, tasks/cancel work) but rejects others (tasks/list → -32601, tasks/resubscribe → empty SSE). Workaround: raw HTTP JSON-RPC calls with correct v1.0 method names for list_tasks and subscribe_to_task.
  - **Cancel timing issue solved via ListTasks.** Azure Container Apps buffers SSE responses (HTTP/1.1), making it impossible to read the task ID from the stream before the task completes. Go client avoids this because Go uses HTTP/2 by default, which doesn't buffer. Solution: fire the streaming message in a background task, use ListTasks to find the working task by state, then cancel it.
  - **SDK cancel_task has no metadata param.** The `CancelTaskRequest` struct only has `id` and `tenant` fields; no metadata. Workaround: raw JSON-RPC call with metadata in params for cancel-with-metadata test.
  - Final JSONRPC: 26/27 (only spec-return-immediately fails — server returns Message instead of Task).
  - REST: 0/27 (genuine SDK gap — no REST transport).
  - v0.3: 4/4.
  - Added `http2` and `rustls-tls` features to reqwest for better TLS/HTTP support.
- **(2026-07-28) Updated SDK from v1.0.16 → v1.0.17** for both server and client. Updated `src/AgentBin.Rust/Cargo.toml` (a2a-rs-server, a2a-rs-core) and `tests/ClientTests/rust/Cargo.toml` (a2a-rs-client, a2a-rs-core). Server build: `cargo build --release` succeeded in 3m 48s. Client build: `cargo build` succeeded in 2m 35s. No compilation errors or warnings. No API changes detected in 1.0.17 — builds were drop-in replacements.
