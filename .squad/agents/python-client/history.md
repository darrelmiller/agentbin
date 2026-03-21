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
