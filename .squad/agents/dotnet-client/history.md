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
