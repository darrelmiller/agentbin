# TypeScript — History

## 2026-03-21 — Initial onboarding

- JS client implemented from a2a-js epic/1.0_breaking_changes branch
- SDK source cloned to D:\github\a2aproject\a2a-js (peer folder)
- Client is relatively new — was built during this session series

## Learnings

### 2026-03-22 — Standalone run.py created
- Created `tests/ClientTests/js/run.py` for independent test execution
- Pattern: `python run.py [base_url]` — auto-installs deps if node_modules missing
- Matches team convention from `run-all.py`: `["node", "test_js_client.mjs"]` with base_url arg

### 2026-03-22 — SDK dependency audit
- package.json uses `file:D:/github/a2aproject/a2a-js` (local file reference)
- SDK repo: branch `epic/1.0_breaking_changes`, dist/ built 2026-03-17 (current with HEAD)
- Installed node_modules has SDK v0.3.10 — this is STALE vs current dist
- ⚠ BREAKING: Latest commit `c29f4f8` removes `JsonRpcTransport` from `@a2a-js/sdk/client`
- Our test client imports `JsonRpcTransport` at lines 23 and 92 of `test_js_client.mjs`
- Running `npm install` now will pull in the new dist and BREAK JSON-RPC tests
- Current state works only because node_modules was installed before the removal commit
- Also: commit `a886b1a` switched to proto-based types — may affect more imports
