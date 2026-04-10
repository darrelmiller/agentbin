# Python — History

## 2026-03-21 — Initial onboarding

- Python client uses official a2a-sdk 1.0.0a0 from PyPI
- 51/58 tests pass (26/27 JSON-RPC, 22/27 REST, 1/4 v0.3)
- v0.3 tests fail because Python SDK sends v1.0 method names to v0.3 agent
- REST has minor issues: cancel-metadata not echoed, subscribe 0 events, error parsing AttributeError
- Needed `pip install a2a-sdk[sqlite]` for SQLAlchemy dependency

## Learnings

### 2026-03-21 — Test runner regression: 2/58 tests due to exception handling gap

**Root cause:** The main test loop used `except Exception` which does NOT catch
`asyncio.CancelledError` (a `BaseException` in Python 3.9+). Leaking async generator
cleanup errors (`RuntimeError: aclose(): asynchronous generator is already running`)
from the SDK could trigger `CancelledError` propagation, killing the loop. When the
loop crashed before writing `results.json`, `run-all.py` read a stale file from a
previous partial run — producing the phantom "2 results" observation.

**Fix (3 changes):**
1. Changed `except Exception` → `except BaseException` (re-raises `KeyboardInterrupt`)
2. Added `asyncio.wait_for(fn(), timeout=30.0)` per-test timeout to prevent hangs
3. Moved `results.json` write into a `finally` block so it's always written, even on crash
4. Added `sys.stdout.flush()` after each test for reliable subprocess output

**Verification:** 58/58 tests execute, 51 pass (same baseline as before regression).

### 2026-03-22 — Standalone runner + SDK dependency audit

**Created `run.py`:** A standalone test runner at `tests/ClientTests/python/run.py` that:
- Accepts optional `[base_url]` CLI arg (defaults to Azure Container Apps URL)
- Auto-installs dependencies from `requirements.txt` if missing
- Delegates to `test_python_client.py` and reads `results.json` for a summary line

**Created `requirements.txt`:** Pinned `a2a-sdk>=1.0.0a0` and `httpx>=0.27.0`.

**SDK dependency audit findings:**
- **Installed:** a2a-sdk 1.0.0a0 (pip, non-editable) in site-packages
- **PyPI latest:** 0.3.25 — the 1.0.0a0 pre-release is NOT published on PyPI
- **Source:** Built from local repo (`D:\github\a2aproject\a2a-python`) and installed via pip
  (no `direct_url.json`, INSTALLER=pip — a wheel was built locally then installed)
- **Local repos:** Both `a2a-python` and `a2a-python-1.0-dev` exist with dynamic versioning
- **Action:** No change — staying on the locally-built 1.0.0a0 as intended

### ⚠ Cross-Team Alert: JS SDK Breaking Change (2026-03-22)

**Alert from TypeScript agent:** The @a2a-js/sdk dependency (epic/1.0_breaking_changes branch) has removed `JsonRpcTransport` from client exports (commit c29f4f8 "Remove JSON-RPC Client #353"). The JS test client will break when `npm install` is run because it imports `JsonRpcTransport`. Additionally, commit a886b1a switched codebase to proto-based types (may require more import changes). The JSON-RPC transport removal appears intentional (architectural decision in the SDK), so tests should likely be adapted to REST-only rather than pinned. No action needed for Python client — this is informational cross-team awareness.

### 2026-03-22 — Added spec-extended-card tests

**Task:** Add `spec-extended-card` acceptance tests for both JSON-RPC and REST bindings to validate the A2A extended agent card feature.

**Implementation:**
- Added `test_spec_extended_card()` for JSON-RPC binding (`jsonrpc/spec-extended-card`)
- Added `test_rest_spec_extended_card()` for REST binding (`rest/spec-extended-card`)
- Both tests follow the same pattern:
  1. Get public agent card and verify `capabilities.extendedAgentCard == true`
  2. Call GetExtendedAgentCard with `Authorization: Bearer agentbin-test-token` header
  3. Verify response is a valid AgentCard with name and skills
  4. Verify extended card has more skills than public card OR has `admin-status` skill
- JSON-RPC test uses POST to `/spec` with `{"jsonrpc":"2.0","method":"GetExtendedAgentCard",...}`
- REST test uses GET to `/spec/extendedAgentCard`
- Since a2a-sdk 1.0.0a0 doesn't have a `get_extended_agent_card()` method, both tests use raw httpx calls
- Added tests to ALL_TESTS list: total tests now 60 (28 JSON-RPC, 28 REST, 4 v0.3)

**Verification:** Syntax check passed with `python -c "import ast; ast.parse(...)"`

### 2026-07-16 — Fixed a2a-sdk 1.0.0a0 → 1.0.0a1 API migration

**Root cause:** The a2a-python local repo was updated to v1.0.0-alpha.1 (or HEAD of main at 0.3.26), breaking the test client and Python server which were written against the alpha.0 API.

**Three breaking changes in alpha.1:**
1. `ClientFactory.connect(url, client_config=config)` (classmethod) removed → replaced by `ClientFactory(config).create_from_url(url)` (instance method)
2. `client.send_message()` now yields raw `StreamResponse` instead of `(StreamResponse, Task)` tuples — caller must extract task from `sr.task` or `sr.status_update`
3. `ClientConfig.streaming` default changed from `False` to `True`
4. Server: `a2a.server.apps.A2AStarletteApplication` removed → use `create_jsonrpc_routes()`, `create_rest_routes()`, `create_agent_card_routes()`; `DefaultRequestHandler` → `DefaultRequestHandlerV2` (takes `agent_card` param)

**Client fixes (test_python_client.py):**
- Updated `make_client()` and `make_v03_client()` to use `ClientFactory(config).create_from_url()`
- Updated all 4 direct `ClientFactory.connect()` calls
- Updated `sdk_send()` to accumulate task state from both `task` and `status_update` streaming events
- Updated all 32 `async for _, task in client.send_message()` unpacking patterns
- Added explicit `streaming=False` to multi-turn test's `ClientConfig`
- Fixed v0.3 `card.url` → `card.supported_interfaces[0].url`

**Server fixes (AgentBin.Python/main.py):**
- Replaced `A2AStarletteApplication` / `A2ARESTFastAPIApplication` with `create_jsonrpc_routes()` / `create_rest_routes()` / `create_agent_card_routes()`
- Replaced `DefaultRequestHandler` with `DefaultRequestHandlerV2`
- Updated `requirements.txt` to pin `a2a-sdk>=1.0.0a0`

**Result:** 56/60 tests pass (up from 4/60). The 4 remaining failures are pre-existing (3 v0.3 compat + 1 REST cancel-metadata) — not caused by this migration.
