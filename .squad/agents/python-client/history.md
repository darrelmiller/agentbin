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
