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

### SDK upgrade: Alpha3 → Beta1-SNAPSHOT (2026-03-21)
- **Completed upgrade** from `io.github.a2asdk:1.0.0.Alpha3` (Maven Central) to `org.a2aproject.sdk:1.0.0.Beta1-SNAPSHOT` (local build)
- Upstream SDK built from `D:\github\a2aproject\a2a-java` with `mvn clean install -DskipTests -Dinvoker.skip=true` (BOM invoker test fails, skip it)
- **API breaking changes found and fixed:**
  - `cancelTask()` now takes `CancelTaskParams` instead of `TaskIdParams` — CancelTaskParams supports metadata field
  - `subscribeToTask()` requires consumers and error handler as method params (not just on builder)
  - `PushNotificationConfig` class removed — `TaskPushNotificationConfig` is now a 6-param record (id, taskId, url, token, authentication, tenant)
- **Behavioral change:** Beta SDK emits `TaskEvent` at SUBMITTED state (not just terminal). All consumer patterns that resolved CompletableFuture on any TaskEvent needed state checks added.
- **Import paths unchanged:** `io.a2a.*` packages are the same despite groupId change
- **Artifact IDs unchanged:** `a2a-java-sdk-client`, `a2a-java-sdk-client-transport-jsonrpc`, `a2a-java-sdk-client-transport-rest`
- **Test results:** 27/58 pass. JSONRPC transport still broken (protobuf serialization: "Parameter 'id' may not be null"), agent card unmarshalling fails on both transports. These are upstream SDK bugs.
- **Cancel-with-metadata test** now actually sends metadata via CancelTaskParams (was impossible with Alpha3's TaskIdParams)

### SDK upgrade: Alpha4 → Beta1-SNAPSHOT (2026-07-28)
- **Pulled latest** from `D:\github\a2aproject\a2a-java` — 10 new commits since Alpha4 tag
- **Built and installed** with `mvn clean install -DskipTests -Dinvoker.skip=true` (exit 0)
- **Updated pom.xml** from `1.0.0.Alpha4` → `1.0.0.Beta1-SNAPSHOT` — compiles cleanly
- **Key changes in Beta1-SNAPSHOT:**
  - `feat(errors): add structured error codes and details (#743)` — `A2AErrorCodes` is now an enum (was interface), `A2AError.getData()` → `getDetails()` (returns `Map<String, Object>`)
  - `feat: Add HTTP caching headers to Agent Card endpoint (#761)` — server-side only
  - `fix: Keep stream open on interrupted state changes (#756)` — may help streaming tests on INPUT_REQUIRED
  - `feat(http-client): prebuilt HttpClient support (#745)` — convenience, no test impact
  - `TaskState` now has `isInterrupted()` method (INPUT_REQUIRED, AUTH_REQUIRED)
  - Various server-side fixes (terminal state rejection, empty Content-Type, etc.)
- **No breaking changes for our test client:** Our code doesn't reference `getData()`, `A2AErrorCodes`, or any of the renamed APIs
- **Null-id bug status: NOT FIXED**
  - Root cause traced: JSONRPC transport deserializes Task responses through protobuf (`JsonFormat.parser()`) → MapStruct mapper → Task constructor
  - MapStruct `TaskMapper` has `@Mapping(target = "id", qualifiedByName = "emptyToNull")` which converts empty string → null
  - `Task.java` constructor still calls `Assert.checkNotNullParam("id", id)` — throws when id is null
  - The structured error codes commit only changed error *reporting*, not Task deserialization
  - This is an upstream SDK architectural issue (protobuf intermediate layer strips/empties the id field)
  - No commits since Alpha4 touched the Task deserialization path in JSONRPCUtils

### Dashboard corrected known failure annotations (2026-07-25)
- Dashboard corrected ~25 Java `KNOWN_FAILURES` annotations in `tests/run-all.py` to properly attribute `InvalidParamsError: Parameter 'id' may not be null` as a **client-side Java SDK issue** (not server rejection)
- **Root cause identified:** Error string lives in `io.a2a.util.Assert.checkNotNullParam` and fires in the `Task` constructor during response deserialization when protobuf yields null task ID
- **Evidence:** .NET server never produces this message and explicitly allows null JSON-RPC envelope `id` per spec
- **Action item for Java team:** When filing upstream issues against `a2a-java` SDK, reference the client-side `Task` constructor as the failure point, not the server
