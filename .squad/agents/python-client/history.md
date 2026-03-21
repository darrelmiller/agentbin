# Python — History

## 2026-03-21 — Initial onboarding

- Python client uses official a2a-sdk 1.0.0a0 from PyPI
- 51/58 tests pass (26/27 JSON-RPC, 22/27 REST, 1/4 v0.3)
- v0.3 tests fail because Python SDK sends v1.0 method names to v0.3 agent
- REST has minor issues: cancel-metadata not echoed, subscribe 0 events, error parsing AttributeError
- Needed `pip install a2a-sdk[sqlite]` for SQLAlchemy dependency
