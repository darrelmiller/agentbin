# DotNet — History

## 2026-03-21 — Initial onboarding

- .NET client uses A2A SDK 1.0.0-preview from NuGet
- 29/58 tests pass (25/27 JSON-RPC, 0/27 REST, 4/4 v0.3)
- All previously-skipped methods (CancelTask, ListTasks, SubscribeToTask, PushConfig) now call real SDK methods
- Cancel tests use streaming pattern to get taskId while task is running
- REST tests all record "SDK does not support" — .NET SDK only has JSON-RPC transport
- IMPORTANT: Must run compiled exe directly, NOT `dotnet run` (kills server process)
- subscribe-to-task fails with "internal error during streaming" — likely server bug

## Learnings

### a2a-dotnet versioning pipeline investigation (2026-03-21)

**Version control files:**
- `src/Directory.Build.props` — THE source of truth for package version. Currently `<Version>1.0.0-preview2</Version>`. Controls both NuGet package version and assembly InformationalVersion.
- `A2A.csproj` — has `<PackageId>A2A</PackageId>` but NO version properties (inherits from Directory.Build.props).
- Root `Directory.Build.props` — no version properties, just compiler settings and strong-naming.
- No `version.props` or other version files exist.

**CI pipeline (release.yaml):**
- For release events: `dotnet pack --configuration Release` with NO version override — version comes entirely from `src/Directory.Build.props`.
- For daily/manual: `dotnet pack --version-suffix "ci.{run_number}"` — produces CI preview packages.
- NuGet.org publish only triggers on GitHub Release events from the `a2aproject/a2a-dotnet` repo.

**Root cause of the observed version mismatch (NuGet `1.0.0-preview` vs DLL `1.0.0-preview2`):**
- The A2A package in the local NuGet cache (`~/.nuget/packages/a2a/1.0.0-preview/`) was NOT restored from NuGet.org. The `.nupkg.metadata` file shows `"source": "D:\\github\\darrelmiller\\agentbin\\nupkgs"`.
- The locally-built `A2A.1.0.0-preview.nupkg` exists at `D:\github\a2aproject\a2a-dotnet\nupkgs`, timestamped March 17 — AFTER the version was bumped to `1.0.0-preview2` in commit `2a7d7b3`.
- The DLLs inside were compiled from source at `1.0.0-preview2` (commit `2a7d7b3`), but the NuGet package version was overridden to `1.0.0-preview` at pack time (likely via `-p:PackageVersion` or `--version-suffix`).
- This is NOT a CI pipeline bug — the actual NuGet.org release (workflow run #257, tag `v1.0.0-preview1`) was built from commit `0664792b` where `<Version>1.0.0-preview</Version>` was correct and consistent.

**Fix:** Clear the NuGet cache (`dotnet nuget locals all --clear`) and restore to get the genuine NuGet.org package. Ensure `nuget.config` doesn't include local `nupkgs/` as a source.

**Minor pipeline concern:** The GitHub release tag `v1.0.0-preview1` doesn't match the source version `1.0.0-preview` — the tag has a trailing "1" that the package does not. This is a naming inconsistency in the release process, not a functional bug.

### Standalone test runner created (2026-07-25)

- Created `tests/ClientTests/dotnet/run.py` — standalone runner that builds with `dotnet build` then runs the compiled exe directly (per charter: never `dotnet run`).
- Usage: `python run.py [base_url]` — default base URL is the Azure Container Apps endpoint.
- Produces `results.json` in the same directory and prints pass/fail summary.
- `run-all.py` still uses `["dotnet", "run", "--"]` (line 89) — should be updated to match.

### SDK dependency audit (2026-07-25)

- **.csproj references:** `A2A 1.0.0-preview` (no A2A.AspNetCore — not needed for client tests).
- **NuGet source:** `nuget.config` points only to `nuget.org` — using published NuGet, NOT local nupkgs.
- **Latest published on NuGet.org:** `1.0.0-preview` — matches .csproj. Up to date with published.
- **Local nupkgs/ folder:** Contains `A2A.1.0.0-alpha.nupkg` and `A2A.AspNetCore.1.0.0-alpha.nupkg` — very stale (alpha vs preview), dated March 13. These are NOT being consumed.
- **Local SDK repo (`a2a-dotnet`):** `src/Directory.Build.props` has `<Version>1.0.0-preview2</Version>`. A `dotnet pack` would produce `1.0.0-preview2` — newer than what's on NuGet.org.
- **Gap:** NuGet.org has `1.0.0-preview`, local repo would produce `1.0.0-preview2`. The `1.0.0-preview2` release has not been published to NuGet.org yet.

### ⚠ Cross-Team Alert: JS SDK Breaking Change (2026-03-22)

**Alert from TypeScript agent:** The @a2a-js/sdk dependency (epic/1.0_breaking_changes branch) has removed `JsonRpcTransport` from client exports (commit c29f4f8 "Remove JSON-RPC Client #353"). The JS test client will break when `npm install` is run because it imports `JsonRpcTransport`. Additionally, commit a886b1a switched codebase to proto-based types (may require more import changes). The JSON-RPC transport removal appears intentional (architectural decision in the SDK), so tests should likely be adapted to REST-only rather than pinned. No action needed for DotNet client — this is informational cross-team awareness.
