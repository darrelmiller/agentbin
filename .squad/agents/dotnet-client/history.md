# DotNet — History

## 2026-03-21 — Initial onboarding

- .NET client uses A2A SDK 1.0.0-preview from NuGet
- 29/58 tests pass (25/27 JSON-RPC, 0/27 REST, 4/4 v0.3)
- All previously-skipped methods (CancelTask, ListTasks, SubscribeToTask, PushConfig) now call real SDK methods
- Cancel tests use streaming pattern to get taskId while task is running
- REST tests all record "SDK does not support" — .NET SDK only has JSON-RPC transport
- IMPORTANT: Must run compiled exe directly, NOT `dotnet run` (kills server process)
- subscribe-to-task fails with "internal error during streaming" — likely server bug
