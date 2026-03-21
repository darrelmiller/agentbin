# GoLang — History

## 2026-03-21 — Initial onboarding

- Go client uses official a2a-go/v2 v2.0.0 from pkg.go.dev
- 51/58 tests pass
- Previously used local replace directive; now uses official release
- Go SDK supports both JSON-RPC and REST transports
- The a2a-go project uses non-standard versioning: module path is /v2 but version = protocol spec version

## Learnings

### 2025-07-22 — Standalone runner & SDK check
- Created `tests/ClientTests/go/run.py` — standalone test runner using `go build` + binary execution
- Runner does: build → run binary → parse results.json → print summary with pass/fail counts
- `go build -o test_go_client.exe .` is more reliable than `go run .` for test execution
- SDK dependency: `github.com/a2aproject/a2a-go/v2 v2.0.0` — only version published to pkg.go.dev
- No replace directive in go.mod — using official published package
- Test results stable: 51/58 pass (same as initial onboarding)
- 7 failures: returnImmediately (2), rest/cancel-with-metadata, rest/subscribe-to-task, v0.3 compat (3)

### ⚠ Cross-Team Alert: JS SDK Breaking Change (2026-03-22)

**Alert from TypeScript agent:** The @a2a-js/sdk dependency (epic/1.0_breaking_changes branch) has removed `JsonRpcTransport` from client exports (commit c29f4f8 "Remove JSON-RPC Client #353"). The JS test client will break when `npm install` is run because it imports `JsonRpcTransport`. Additionally, commit a886b1a switched codebase to proto-based types (may require more import changes). The JSON-RPC transport removal appears intentional (architectural decision in the SDK), so tests should likely be adapted to REST-only rather than pinned. No action needed for Go client — this is informational cross-team awareness.
