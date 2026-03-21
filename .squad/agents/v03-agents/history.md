# Legacy — History

## 2026-03-21 — Initial onboarding

- v0.3 agent at /spec03 speaks only v0.3 protocol
- V03EndpointHandler.cs handles v0.3 JSON-RPC method name translation
- .NET client: 4/4 v0.3 tests pass
- Python client: 1/4 v0.3 tests pass (SDK sends v1.0 method names)
- Go client: v0.3 tests in 51/58 overall count
- Known issue: Python SDK doesn't negotiate down to v0.3 method names
