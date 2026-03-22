# TypeScript — History

## 2026-03-21 — Initial onboarding

- JS client implemented from a2a-js epic/1.0_breaking_changes branch
- SDK source cloned to D:\github\a2aproject\a2a-js (peer folder)
- Client is relatively new — was built during this session series

## Learnings

### 2026-03-22 — V1 compatibility layer built

- Created `v1_compat.mjs` to bridge SDK v0.3.10 (proto-based) with V1.0 server wire format
- **Three incompatibilities solved**:
  1. JSON-RPC method names: SDK sends `message/send` → server expects `SendMessage`
  2. Message field naming: SDK serializes `content` → server expects `parts`
  3. Task state spelling: Server sends `TASK_STATE_CANCELED` (American) → SDK expects `TASK_STATE_CANCELLED` (British)
- **JsonRpcTransport NOT removed** — earlier audit was wrong, it's still exported
- SDK's `AgentCapabilities.fromJSON` reads `streaming` not `supportsStreaming` — card normalization needed
- `CancelTaskRequest.toJSON` drops metadata — must preserve it manually
- `GetTaskRequest.toJSON` omits `historyLength: 0` (proto3 default elision)
- Proto3 default elision also drops `blocking: false` from wire format
- REST transport sends cancel with no body — metadata can't be forwarded via REST
- REST subscribe endpoint returns 404 (server doesn't implement it)
- Test score: **49/58** (was 13/58 before changes)

### 2026-03-22 — Standalone run.py created
- Created `tests/ClientTests/js/run.py` for independent test execution
- Pattern: `python run.py [base_url]` — auto-installs deps if node_modules missing
- Matches team convention from `run-all.py`: `["node", "test_js_client.mjs"]` with base_url arg

### 2026-03-22 — SDK dependency audit
- package.json uses `file:D:/github/a2aproject/a2a-js` (local file reference)
- SDK repo: branch `epic/1.0_breaking_changes`, dist/ built 2026-03-17 (current with HEAD)
- SDK v0.3.10 uses proto-based types (numeric enums, `$case` discriminated unions)
- `fromJSON`/`toJSON` on SDK types handle wire ↔ proto conversion
