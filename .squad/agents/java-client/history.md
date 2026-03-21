# Java — History

## 2026-03-21 — Initial onboarding

- Java client was rewritten during SDK upgrade cycle
- Uses local Java SDK source in test-java-sdk/ directory
- SDK not yet published to Maven Central
- Status needs review after prior rewrite

## Learnings

### SDK dependency audit (2026-03-21)
- pom.xml uses groupId `io.github.a2asdk` version `1.0.0.Alpha3` — these are **published Maven Central** artifacts
- The `_remote.repositories` file confirms Alpha3 jars were fetched from `central` (Maven Central)
- Local `.m2` also has `1.0.0.Alpha4-SNAPSHOT` jars (locally installed, no remote origin)
- Upstream SDK at `D:\github\a2aproject\a2a-java` uses groupId `org.a2aproject.sdk` version `1.0.0.Beta1-SNAPSHOT` — **different groupId** from what pom.xml references
- The history note about "uses local Java SDK source in test-java-sdk/" is outdated — pom.xml actually pulls from Maven Central
- Alpha3 is two versions behind upstream (Alpha3 → Alpha4-SNAPSHOT → Beta1-SNAPSHOT)

### Standalone runner (2026-03-21)
- Created `tests/ClientTests/java/run.py` matching Go runner pattern
- Uses separate compile + exec:java steps with `shell=True` on Windows for `mvn.cmd` compatibility
- Produces summary with pass/fail counts from results.json

### ⚠ Cross-Team Alert: JS SDK Breaking Change (2026-03-22)

**Alert from TypeScript agent:** The @a2a-js/sdk dependency (epic/1.0_breaking_changes branch) has removed `JsonRpcTransport` from client exports (commit c29f4f8 "Remove JSON-RPC Client #353"). The JS test client will break when `npm install` is run because it imports `JsonRpcTransport`. Additionally, commit a886b1a switched codebase to proto-based types (may require more import changes). The JSON-RPC transport removal appears intentional (architectural decision in the SDK), so tests should likely be adapted to REST-only rather than pinned. No action needed for Java client — this is informational cross-team awareness.
