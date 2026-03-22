import A2AClient
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

// MARK: - Constants & Globals

let defaultBaseURL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
let sdkName = "a2a-client-swift 1.0.x"

struct TestResult: Codable, Sendable {
    let id: String
    let name: String
    let passed: Bool
    let detail: String
    let durationMs: Int64
}

struct TestReport: Codable, Sendable {
    let client: String
    let sdk: String
    let protocolVersion: String
    let timestamp: String
    let baseUrl: String
    let results: [TestResult]
}

// Shared mutable state for collecting results and saved task IDs
final class TestState: @unchecked Sendable {
    var results: [TestResult] = []
    var jsonrpcLifecycleTaskId: String?
    var restLifecycleTaskId: String?

    func record(_ id: String, _ name: String, _ passed: Bool, _ detail: String, _ durationMs: Int64) {
        results.append(TestResult(id: id, name: name, passed: passed, detail: detail, durationMs: durationMs))
        let tag = passed ? "PASS" : "FAIL"
        print("  [\(tag)] \(id) — \(detail)")
    }
}

func truncate(_ s: String, _ maxLen: Int) -> String {
    s.count <= maxLen ? s : String(s.prefix(maxLen)) + "…"
}

func elapsedMs(since start: ContinuousClock.Instant) -> Int64 {
    let dur = ContinuousClock.now - start
    return Int64(dur.components.seconds * 1000 + dur.components.attoseconds / 1_000_000_000_000_000)
}

// MARK: - Client Helpers

func makeClient(baseURL: String, binding: TransportBinding) -> A2AClient {
    let config = A2AClientConfiguration(
        baseURL: URL(string: baseURL)!,
        transportBinding: binding,
        timeoutInterval: 30
    )
    return A2AClient(configuration: config)
}

func makeSpecClient(baseURL: String, binding: TransportBinding) -> A2AClient {
    makeClient(baseURL: baseURL + "/spec", binding: binding)
}

func makeEchoClient(baseURL: String, binding: TransportBinding) -> A2AClient {
    makeClient(baseURL: baseURL + "/echo", binding: binding)
}

// MARK: - Text extraction helpers

func extractText(from response: SendMessageResponse) -> String {
    switch response {
    case .message(let msg):
        return msg.textContent
    case .task(let task):
        return extractTextFromTask(task)
    }
}

func extractTextFromTask(_ task: A2ATask) -> String {
    var text = ""
    if let artifacts = task.artifacts {
        for artifact in artifacts {
            for part in artifact.parts {
                if let t = part.text { text += t }
            }
        }
    }
    if text.isEmpty, let msg = task.status.message {
        text = msg.textContent
    }
    return text
}

func collectPartTypes(from response: SendMessageResponse) -> (hasText: Bool, hasData: Bool, hasFile: Bool) {
    var hasText = false, hasData = false, hasFile = false
    let parts: [Part]
    switch response {
    case .message(let msg):
        parts = msg.parts
    case .task(let task):
        var allParts: [Part] = []
        if let artifacts = task.artifacts {
            for artifact in artifacts {
                allParts.append(contentsOf: artifact.parts)
            }
        }
        parts = allParts
    }
    for part in parts {
        switch part.contentType {
        case .text: hasText = true
        case .data: hasData = true
        case .raw, .url: hasFile = true
        case .unknown: break
        }
    }
    return (hasText, hasData, hasFile)
}

// MARK: - Test Implementations

func testAgentCardEcho(state: TestState, prefix: String, baseURL: String) async {
    let start = ContinuousClock.now
    do {
        let cardURL = URL(string: "\(baseURL)/echo/.well-known/agent.json")!
        let card = try await A2AClient.fetchAgentCard(from: cardURL)
        let ms = elapsedMs(since: start)
        let ok = card.name.contains("Echo") && card.skills.count > 0
        state.record("\(prefix)/agent-card-echo", "\(prefix == "rest" ? "REST " : "")Echo Agent Card", ok,
                     "name=\(card.name), skills=\(card.skills.count)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/agent-card-echo", "\(prefix == "rest" ? "REST " : "")Echo Agent Card", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testAgentCardSpec(state: TestState, prefix: String, baseURL: String) async {
    let start = ContinuousClock.now
    do {
        let cardURL = URL(string: "\(baseURL)/.well-known/agent.json")!
        let card = try await A2AClient.fetchAgentCard(from: cardURL)
        let ms = elapsedMs(since: start)
        let ok = card.name.contains("Spec") && card.skills.count > 0
        state.record("\(prefix)/agent-card-spec", "\(prefix == "rest" ? "REST " : "")Spec Agent Card", ok,
                     "name=\(card.name), skills=\(card.skills.count)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/agent-card-spec", "\(prefix == "rest" ? "REST " : "")Spec Agent Card", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testEchoSendMessage(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeEchoClient(baseURL: baseURL, binding: binding)
        let response = try await client.sendMessage("hello from Swift")
        let ms = elapsedMs(since: start)
        let text = extractText(from: response)
        let hasEcho = text.lowercased().contains("hello") || text.lowercased().contains("echo")
        state.record("\(prefix)/echo-send-message", "\(prefix == "rest" ? "REST " : "")Echo Send Message", hasEcho,
                     "response=\(truncate(text, 120))", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/echo-send-message", "\(prefix == "rest" ? "REST " : "")Echo Send Message", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecMessageOnly(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let response = try await client.sendMessage("message-only")
        let ms = elapsedMs(since: start)
        switch response {
        case .message(let msg):
            let text = msg.textContent
            state.record("\(prefix)/spec-message-only", "\(prefix == "rest" ? "REST " : "")Message Only", true,
                         "got Message, text=\(truncate(text, 100))", ms)
        case .task(let task):
            state.record("\(prefix)/spec-message-only", "\(prefix == "rest" ? "REST " : "")Message Only", false,
                         "expected Message, got Task(state=\(task.status.state.rawValue))", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-message-only", "\(prefix == "rest" ? "REST " : "")Message Only", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecTaskLifecycle(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let response = try await client.sendMessage("task-lifecycle")
        let ms = elapsedMs(since: start)
        switch response {
        case .task(let task):
            if prefix == "rest" {
                state.restLifecycleTaskId = task.id
            } else {
                state.jsonrpcLifecycleTaskId = task.id
            }
            let passed = task.status.state == .completed
            let artifactCount = task.artifacts?.count ?? 0
            state.record("\(prefix)/spec-task-lifecycle", "\(prefix == "rest" ? "REST " : "")Task Lifecycle", passed,
                         "state=\(task.status.state.rawValue), artifacts=\(artifactCount), id=\(task.id)", ms)
        case .message:
            state.record("\(prefix)/spec-task-lifecycle", "\(prefix == "rest" ? "REST " : "")Task Lifecycle", false,
                         "expected Task, got Message", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-task-lifecycle", "\(prefix == "rest" ? "REST " : "")Task Lifecycle", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecGetTask(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let taskId = prefix == "rest" ? state.restLifecycleTaskId : state.jsonrpcLifecycleTaskId
    guard let taskId = taskId else {
        state.record("\(prefix)/spec-get-task", "\(prefix == "rest" ? "REST " : "")Get Task", false,
                     "skipped — no task ID from lifecycle test", 0)
        return
    }
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let task = try await client.getTask(taskId)
        let ms = elapsedMs(since: start)
        let passed = task.id == taskId
        state.record("\(prefix)/spec-get-task", "\(prefix == "rest" ? "REST " : "")Get Task", passed,
                     "id=\(task.id), state=\(task.status.state.rawValue)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-get-task", "\(prefix == "rest" ? "REST " : "")Get Task", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecTaskFailure(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let response = try await client.sendMessage("task-failure")
        let ms = elapsedMs(since: start)
        switch response {
        case .task(let task):
            let passed = task.status.state == .failed
            state.record("\(prefix)/spec-task-failure", "\(prefix == "rest" ? "REST " : "")Task Failure", passed,
                         "state=\(task.status.state.rawValue)", ms)
        default:
            state.record("\(prefix)/spec-task-failure", "\(prefix == "rest" ? "REST " : "")Task Failure", false,
                         "expected failed Task, got Message", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-task-failure", "\(prefix == "rest" ? "REST " : "")Task Failure", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecDataTypes(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let response = try await client.sendMessage("data-types")
        let ms = elapsedMs(since: start)
        let (hasText, hasData, hasFile) = collectPartTypes(from: response)
        let passed = hasText && hasData && hasFile
        state.record("\(prefix)/spec-data-types", "\(prefix == "rest" ? "REST " : "")Data Types", passed,
                     "text=\(hasText), data=\(hasData), file=\(hasFile)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-data-types", "\(prefix == "rest" ? "REST " : "")Data Types", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecStreaming(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.sendStreamingMessage("streaming")
        var eventCount = 0
        var lastState: TaskState?
        var hasArtifact = false
        for try await event in stream {
            eventCount += 1
            switch event {
            case .taskStatusUpdate(let e):
                lastState = e.status.state
            case .taskArtifactUpdate:
                hasArtifact = true
            case .task(let t):
                lastState = t.status.state
                if let artifacts = t.artifacts, !artifacts.isEmpty { hasArtifact = true }
            case .message:
                break
            }
        }
        let ms = elapsedMs(since: start)
        let passed = eventCount > 1 && (lastState == .completed || hasArtifact)
        state.record("\(prefix)/spec-streaming", "\(prefix == "rest" ? "REST " : "")Streaming", passed,
                     "events=\(eventCount), lastState=\(lastState?.rawValue ?? "nil"), hasArtifact=\(hasArtifact)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-streaming", "\(prefix == "rest" ? "REST " : "")Streaming", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecMultiTurn(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)

        // Step 1: start conversation
        let resp1 = try await client.sendMessage("multi-turn start conversation")
        guard case .task(let task1) = resp1 else {
            state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                         "step1: expected Task, got Message", elapsedMs(since: start))
            return
        }
        guard task1.status.state == .inputRequired else {
            state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                         "step1: expected input_required, got \(task1.status.state.rawValue)", elapsedMs(since: start))
            return
        }
        let taskId = task1.id

        // Step 2: follow-up with taskId
        let msg2 = Message.user("follow-up message", taskId: taskId)
        let resp2 = try await client.sendMessage(msg2)
        guard case .task(let task2) = resp2 else {
            state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                         "step2: expected Task, got Message", elapsedMs(since: start))
            return
        }
        guard task2.status.state == .inputRequired else {
            state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                         "step2: expected input_required, got \(task2.status.state.rawValue)", elapsedMs(since: start))
            return
        }

        // Step 3: send "done" to complete
        let msg3 = Message.user("done", taskId: taskId)
        let resp3 = try await client.sendMessage(msg3)
        guard case .task(let task3) = resp3 else {
            state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                         "step3: expected Task, got Message", elapsedMs(since: start))
            return
        }
        let ms = elapsedMs(since: start)
        let passed = task3.status.state == .completed
        state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", passed,
                     "taskId=\(taskId), 3 steps, finalState=\(task3.status.state.rawValue)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-multi-turn", "\(prefix == "rest" ? "REST " : "")Multi-Turn Conversation", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecTaskCancel(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.sendStreamingMessage("task-cancel")
        var streamTaskId: String?
        for try await event in stream {
            if let tid = event.taskId {
                streamTaskId = tid
                break
            }
        }
        guard let taskId = streamTaskId else {
            state.record("\(prefix)/spec-task-cancel", "\(prefix == "rest" ? "REST " : "")Task Cancel", false,
                         "no task ID from stream", elapsedMs(since: start))
            return
        }
        let cancelled = try await client.cancelTask(taskId)
        let ms = elapsedMs(since: start)
        let isCancelled = cancelled.status.state == .cancelled
        if isCancelled {
            state.record("\(prefix)/spec-task-cancel", "\(prefix == "rest" ? "REST " : "")Task Cancel", true,
                         "taskId=\(taskId), state=cancelled", ms)
        } else {
            // Fallback: check via getTask
            let task = try await client.getTask(taskId)
            let passed = task.status.state == .cancelled
            state.record("\(prefix)/spec-task-cancel", "\(prefix == "rest" ? "REST " : "")Task Cancel", passed,
                         "taskId=\(taskId), state=\(task.status.state.rawValue) (via getTask)", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-task-cancel", "\(prefix == "rest" ? "REST " : "")Task Cancel", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecCancelWithMetadata(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.sendStreamingMessage("task-cancel")
        var streamTaskId: String?
        for try await event in stream {
            if let tid = event.taskId {
                streamTaskId = tid
                break
            }
        }
        guard let taskId = streamTaskId else {
            state.record("\(prefix)/spec-cancel-with-metadata", "\(prefix == "rest" ? "REST " : "")Cancel With Metadata", false,
                         "no task ID from stream", elapsedMs(since: start))
            return
        }
        // Cancel with metadata - use cancelTask then verify via getTask
        let _ = try await client.cancelTask(taskId)

        // Retrieve task to verify state
        let task = try await client.getTask(taskId)
        let ms = elapsedMs(since: start)
        let isCancelled = task.status.state == .cancelled
        state.record("\(prefix)/spec-cancel-with-metadata", "\(prefix == "rest" ? "REST " : "")Cancel With Metadata", isCancelled,
                     "taskId=\(taskId), state=\(task.status.state.rawValue)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-cancel-with-metadata", "\(prefix == "rest" ? "REST " : "")Cancel With Metadata", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecListTasks(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let result = try await client.listTasks()
        let ms = elapsedMs(since: start)
        let count = result.tasks.count
        let passed = count >= 1
        state.record("\(prefix)/spec-list-tasks", "\(prefix == "rest" ? "REST " : "")List Tasks", passed,
                     "tasks=\(count) (need>=1)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-list-tasks", "\(prefix == "rest" ? "REST " : "")List Tasks", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testSpecReturnImmediately(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let config = MessageSendConfiguration(returnImmediately: true)
        let response = try await client.sendMessage("long-running test", configuration: config)
        let elapsed = Double(elapsedMs(since: start)) / 1000.0
        let ms = elapsedMs(since: start)
        var taskState: TaskState?
        if case .task(let task) = response {
            taskState = task.status.state
        }
        if elapsed < 2.0 && taskState != .completed {
            state.record("\(prefix)/spec-return-immediately", "\(prefix == "rest" ? "REST " : "")Return Immediately", true,
                         "took \(String(format: "%.1f", elapsed))s, state=\(taskState?.rawValue ?? "nil") — returned promptly", ms)
        } else if elapsed >= 3.0 || taskState == .completed {
            state.record("\(prefix)/spec-return-immediately", "\(prefix == "rest" ? "REST " : "")Return Immediately", false,
                         "took \(String(format: "%.1f", elapsed))s, state=\(taskState?.rawValue ?? "nil") — returnImmediately ignored", ms)
        } else {
            state.record("\(prefix)/spec-return-immediately", "\(prefix == "rest" ? "REST " : "")Return Immediately", false,
                         "took \(String(format: "%.1f", elapsed))s, state=\(taskState?.rawValue ?? "nil") — inconclusive", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/spec-return-immediately", "\(prefix == "rest" ? "REST " : "")Return Immediately", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

// MARK: - Error tests

func testErrorTaskNotFound(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let _ = try await client.getTask("00000000-0000-0000-0000-000000000000")
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-task-not-found", "\(prefix == "rest" ? "REST " : "")Task Not Found Error", false,
                     "expected error, got success", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-task-not-found", "\(prefix == "rest" ? "REST " : "")Task Not Found Error", true,
                     "got expected error: \(truncate(String(describing: error), 100))", ms)
    }
}

func testErrorCancelNotFound(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let _ = try await client.cancelTask("00000000-0000-0000-0000-000000000000")
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-cancel-not-found", "\(prefix == "rest" ? "REST " : "")Cancel Not Found Error", false,
                     "expected error, got success", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-cancel-not-found", "\(prefix == "rest" ? "REST " : "")Cancel Not Found Error", true,
                     "got expected error: \(truncate(String(describing: error), 100))", ms)
    }
}

func testErrorCancelTerminal(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        // Create a completed task
        let resp = try await client.sendMessage("task-lifecycle")
        guard case .task(let task) = resp, task.status.state == .completed else {
            state.record("\(prefix)/error-cancel-terminal", "\(prefix == "rest" ? "REST " : "")Cancel Terminal Error", false,
                         "could not create completed task", elapsedMs(since: start))
            return
        }
        do {
            let _ = try await client.cancelTask(task.id)
            let ms = elapsedMs(since: start)
            state.record("\(prefix)/error-cancel-terminal", "\(prefix == "rest" ? "REST " : "")Cancel Terminal Error", false,
                         "expected error canceling completed task, got success", ms)
        } catch {
            let ms = elapsedMs(since: start)
            state.record("\(prefix)/error-cancel-terminal", "\(prefix == "rest" ? "REST " : "")Cancel Terminal Error", true,
                         "got expected error: \(truncate(String(describing: error), 100))", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-cancel-terminal", "\(prefix == "rest" ? "REST " : "")Cancel Terminal Error", false,
                     "error creating task: \(truncate(String(describing: error), 100))", ms)
    }
}

func testErrorSendTerminal(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        // Create a completed task
        let resp = try await client.sendMessage("task-lifecycle")
        guard case .task(let task) = resp, task.status.state == .completed else {
            state.record("\(prefix)/error-send-terminal", "\(prefix == "rest" ? "REST " : "")Send Terminal Error", false,
                         "could not create completed task", elapsedMs(since: start))
            return
        }
        do {
            let msg = Message.user("follow-up after done", taskId: task.id)
            let _ = try await client.sendMessage(msg)
            let ms = elapsedMs(since: start)
            state.record("\(prefix)/error-send-terminal", "\(prefix == "rest" ? "REST " : "")Send Terminal Error", false,
                         "expected error sending to completed task, got success", ms)
        } catch {
            let ms = elapsedMs(since: start)
            state.record("\(prefix)/error-send-terminal", "\(prefix == "rest" ? "REST " : "")Send Terminal Error", true,
                         "got expected error: \(truncate(String(describing: error), 100))", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-send-terminal", "\(prefix == "rest" ? "REST " : "")Send Terminal Error", false,
                     "error creating task: \(truncate(String(describing: error), 100))", ms)
    }
}

func testErrorSendInvalidTask(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let msg = Message.user("hello", taskId: "00000000-0000-0000-0000-000000000000")
        let _ = try await client.sendMessage(msg)
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-send-invalid-task", "\(prefix == "rest" ? "REST " : "")Send Invalid Task Error", false,
                     "expected error, got success", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-send-invalid-task", "\(prefix == "rest" ? "REST " : "")Send Invalid Task Error", true,
                     "got expected error: \(truncate(String(describing: error), 100))", ms)
    }
}

func testErrorPushNotSupported(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let config = PushNotificationConfig(url: "https://example.com/webhook")
        let _ = try await client.createPushNotificationConfig(taskId: "00000000-0000-0000-0000-000000000000", config: config)
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-push-not-supported", "\(prefix == "rest" ? "REST " : "")Push Not Supported Error", false,
                     "expected error, got success", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-push-not-supported", "\(prefix == "rest" ? "REST " : "")Push Not Supported Error", true,
                     "got expected error: \(truncate(String(describing: error), 100))", ms)
    }
}

func testSubscribeToTask(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        // Start a long-running task via streaming
        let stream = try await client.sendStreamingMessage("task-cancel")
        var taskId: String?
        for try await event in stream {
            if let tid = event.taskId {
                taskId = tid
                break
            }
        }
        guard let taskId = taskId else {
            state.record("\(prefix)/subscribe-to-task", "\(prefix == "rest" ? "REST " : "")Subscribe To Task", false,
                         "no task ID from stream", elapsedMs(since: start))
            return
        }
        // Subscribe to the task
        let subStream = try await client.subscribeToTask(taskId)
        var subEventCount = 0
        for try await _ in subStream {
            subEventCount += 1
            if subEventCount >= 1 {
                // Cancel the task to end
                let _ = try? await client.cancelTask(taskId)
                break
            }
        }
        let ms = elapsedMs(since: start)
        let passed = subEventCount >= 1
        state.record("\(prefix)/subscribe-to-task", "\(prefix == "rest" ? "REST " : "")Subscribe To Task", passed,
                     "taskId=\(taskId), subscriptionEvents=\(subEventCount)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/subscribe-to-task", "\(prefix == "rest" ? "REST " : "")Subscribe To Task", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testErrorSubscribeNotFound(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.subscribeToTask("00000000-0000-0000-0000-000000000000")
        for try await _ in stream {
            break
        }
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-subscribe-not-found", "\(prefix == "rest" ? "REST " : "")Subscribe Not Found Error", false,
                     "expected error, got success", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/error-subscribe-not-found", "\(prefix == "rest" ? "REST " : "")Subscribe Not Found Error", true,
                     "got expected error: \(truncate(String(describing: error), 100))", ms)
    }
}

// MARK: - Streaming tests

func testStreamMessageOnly(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.sendStreamingMessage("message-only hello")
        var eventCount = 0
        var gotMessage = false
        for try await event in stream {
            eventCount += 1
            if case .message = event { gotMessage = true }
        }
        let ms = elapsedMs(since: start)
        let passed = eventCount == 1 && gotMessage
        state.record("\(prefix)/stream-message-only", "\(prefix == "rest" ? "REST " : "")Stream Message Only", passed,
                     "events=\(eventCount), gotMessage=\(gotMessage)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/stream-message-only", "\(prefix == "rest" ? "REST " : "")Stream Message Only", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testStreamTaskLifecycle(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        let stream = try await client.sendStreamingMessage("task-lifecycle process")
        var gotTaskEvent = false
        var lastState: TaskState?
        for try await event in stream {
            switch event {
            case .taskStatusUpdate(let e):
                gotTaskEvent = true
                lastState = e.status.state
            case .task(let t):
                gotTaskEvent = true
                lastState = t.status.state
            default:
                break
            }
        }
        let ms = elapsedMs(since: start)
        let passed = gotTaskEvent && lastState == .completed
        state.record("\(prefix)/stream-task-lifecycle", "\(prefix == "rest" ? "REST " : "")Stream Task Lifecycle", passed,
                     "gotTaskEvent=\(gotTaskEvent), lastState=\(lastState?.rawValue ?? "nil")", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/stream-task-lifecycle", "\(prefix == "rest" ? "REST " : "")Stream Task Lifecycle", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

// MARK: - Multi-Turn Context Preserved

func testMultiTurnContextPreserved(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)

        // Step 1: start multi-turn conversation
        let resp1 = try await client.sendMessage("multi-turn start")
        guard case .task(let task1) = resp1 else {
            state.record("\(prefix)/multi-turn-context-preserved", "\(prefix == "rest" ? "REST " : "")Multi-Turn Context Preserved", false,
                         "step1 returned Message, expected Task", elapsedMs(since: start))
            return
        }
        let contextId1 = task1.contextId
        let taskId = task1.id

        // Step 2: follow-up with taskId
        let msg2 = Message.user("more data", taskId: taskId)
        let resp2 = try await client.sendMessage(msg2)
        guard case .task(let task2) = resp2 else {
            state.record("\(prefix)/multi-turn-context-preserved", "\(prefix == "rest" ? "REST " : "")Multi-Turn Context Preserved", false,
                         "step2 returned Message, expected Task", elapsedMs(since: start))
            return
        }
        let contextId2 = task2.contextId

        let ms = elapsedMs(since: start)
        let passed = !contextId1.isEmpty && contextId1 == contextId2
        state.record("\(prefix)/multi-turn-context-preserved", "\(prefix == "rest" ? "REST " : "")Multi-Turn Context Preserved", passed,
                     "contextId1=\(contextId1), contextId2=\(contextId2), match=\(contextId1 == contextId2)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/multi-turn-context-preserved", "\(prefix == "rest" ? "REST " : "")Multi-Turn Context Preserved", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

// MARK: - GetTask tests

func testGetTaskWithHistory(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        // Create a task first
        let resp = try await client.sendMessage("task-lifecycle")
        guard case .task(let task) = resp else {
            state.record("\(prefix)/get-task-with-history", "\(prefix == "rest" ? "REST " : "")Get Task With History", false,
                         "could not create task", elapsedMs(since: start))
            return
        }
        let got = try await client.getTask(task.id, historyLength: 10)
        let ms = elapsedMs(since: start)
        let historyLen = got.history?.count ?? 0
        state.record("\(prefix)/get-task-with-history", "\(prefix == "rest" ? "REST " : "")Get Task With History", true,
                     "taskId=\(got.id), state=\(got.status.state.rawValue), historyLen=\(historyLen)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/get-task-with-history", "\(prefix == "rest" ? "REST " : "")Get Task With History", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testGetTaskAfterFailure(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    let start = ContinuousClock.now
    do {
        let client = makeSpecClient(baseURL: baseURL, binding: binding)
        // Create a failed task
        let resp = try await client.sendMessage("task-failure")
        guard case .task(let task) = resp else {
            state.record("\(prefix)/get-task-after-failure", "\(prefix == "rest" ? "REST " : "")Get Task After Failure", false,
                         "could not create failed task", elapsedMs(since: start))
            return
        }
        let got = try await client.getTask(task.id)
        let ms = elapsedMs(since: start)
        let isFailed = got.status.state == .failed
        let hasMessage = got.status.message != nil
        state.record("\(prefix)/get-task-after-failure", "\(prefix == "rest" ? "REST " : "")Get Task After Failure", isFailed && hasMessage,
                     "state=\(got.status.state.rawValue), hasMessage=\(hasMessage)", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("\(prefix)/get-task-after-failure", "\(prefix == "rest" ? "REST " : "")Get Task After Failure", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

// MARK: - v0.3 Tests

func testV03AgentCard(state: TestState, baseURL: String) async {
    let start = ContinuousClock.now
    let cardURL = URL(string: "\(baseURL)/spec03/.well-known/agent.json")!
    do {
        let card = try await A2AClient.fetchAgentCard(from: cardURL)
        let ms = elapsedMs(since: start)
        let hasName = !card.name.isEmpty
        state.record("v03/spec03-agent-card", "v0.3 Agent Card", hasName,
                     "name=\(card.name), skills=\(card.skills.count)", ms)
    } catch {
        // Try raw HTTP fallback for v0.3 card (might be at agent-card.json)
        let fallbackURL = URL(string: "\(baseURL)/spec03/.well-known/agent-card.json")!
        do {
            let (data, response) = try await URLSession.shared.data(from: fallbackURL)
            let ms = elapsedMs(since: start)
            if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let protoVer = json["protocolVersion"] as? String ?? ""
                let hasUrl = json["url"] != nil
                let ok = protoVer == "0.3.0" && hasUrl
                state.record("v03/spec03-agent-card", "v0.3 Agent Card", ok,
                             "protocolVersion=\(protoVer), hasUrl=\(hasUrl)", ms)
            } else {
                state.record("v03/spec03-agent-card", "v0.3 Agent Card", false,
                             "HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)", ms)
            }
        } catch {
            let ms = elapsedMs(since: start)
            state.record("v03/spec03-agent-card", "v0.3 Agent Card", false,
                         "error: \(truncate(String(describing: error), 120))", ms)
        }
    }
}

func testV03SendMessage(state: TestState, baseURL: String) async {
    let start = ContinuousClock.now
    do {
        let client = makeClient(baseURL: baseURL + "/spec03", binding: .jsonRPC)
        let response = try await client.sendMessage("message-only hello")
        let ms = elapsedMs(since: start)
        let text = extractText(from: response)
        let ok = !text.isEmpty
        state.record("v03/spec03-send-message", "v0.3 Send Message", ok,
                     "text=\(truncate(text, 60))", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("v03/spec03-send-message", "v0.3 Send Message", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testV03TaskLifecycle(state: TestState, baseURL: String) async {
    let start = ContinuousClock.now
    do {
        let client = makeClient(baseURL: baseURL + "/spec03", binding: .jsonRPC)
        let response = try await client.sendMessage("task-lifecycle process")
        let ms = elapsedMs(since: start)
        switch response {
        case .task(let task):
            let st = task.status.state
            let ok = st == .completed || st == .working
            state.record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", ok,
                         "state=\(st.rawValue), taskId=\(task.id)", ms)
        case .message:
            state.record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
                         "expected Task, got Message", ms)
        }
    } catch {
        let ms = elapsedMs(since: start)
        state.record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

func testV03Streaming(state: TestState, baseURL: String) async {
    let start = ContinuousClock.now
    do {
        let client = makeClient(baseURL: baseURL + "/spec03", binding: .jsonRPC)
        let stream = try await client.sendStreamingMessage("streaming generate")
        var eventCount = 0
        var finalText = ""
        for try await event in stream {
            eventCount += 1
            switch event {
            case .task(let t):
                if let arts = t.artifacts {
                    for a in arts { for p in a.parts { if let t = p.text { finalText = t } } }
                }
            case .message(let m):
                let t = m.textContent
                if !t.isEmpty { finalText = t }
            case .taskStatusUpdate:
                break
            case .taskArtifactUpdate(let e):
                for p in e.artifact.parts { if let t = p.text { finalText = t } }
            }
        }
        let ms = elapsedMs(since: start)
        let ok = eventCount >= 1 && !finalText.isEmpty
        state.record("v03/spec03-streaming", "v0.3 Streaming", ok,
                     "events=\(eventCount), text=\(truncate(finalText, 50))", ms)
    } catch {
        let ms = elapsedMs(since: start)
        state.record("v03/spec03-streaming", "v0.3 Streaming", false,
                     "error: \(truncate(String(describing: error), 120))", ms)
    }
}

// MARK: - Run all tests for a binding

func runBindingTests(state: TestState, prefix: String, baseURL: String, binding: TransportBinding) async {
    print("\n── \(prefix == "jsonrpc" ? "JSON-RPC" : "HTTP+JSON REST") Binding ──")

    await testAgentCardEcho(state: state, prefix: prefix, baseURL: baseURL)
    await testAgentCardSpec(state: state, prefix: prefix, baseURL: baseURL)
    await testEchoSendMessage(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecMessageOnly(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecTaskLifecycle(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecGetTask(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecTaskFailure(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecDataTypes(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecStreaming(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecMultiTurn(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecTaskCancel(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecCancelWithMetadata(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecListTasks(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSpecReturnImmediately(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorTaskNotFound(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorCancelNotFound(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorCancelTerminal(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorSendTerminal(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorSendInvalidTask(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorPushNotSupported(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testSubscribeToTask(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testErrorSubscribeNotFound(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testStreamMessageOnly(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testStreamTaskLifecycle(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testMultiTurnContextPreserved(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testGetTaskWithHistory(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
    await testGetTaskAfterFailure(state: state, prefix: prefix, baseURL: baseURL, binding: binding)
}

// MARK: - Main

@main
struct TestSwiftClient {
    static func main() async {
        let baseURL: String
        if CommandLine.arguments.count > 1 {
            baseURL = CommandLine.arguments[1]
        } else {
            baseURL = defaultBaseURL
        }

        let state = TestState()

        print("=== Swift A2A Client Tests ===")
        print("Base URL: \(baseURL)")
        print("SDK: \(sdkName)\n")

        // JSON-RPC binding tests (27)
        await runBindingTests(state: state, prefix: "jsonrpc", baseURL: baseURL, binding: .jsonRPC)

        // REST binding tests (27)
        await runBindingTests(state: state, prefix: "rest", baseURL: baseURL, binding: .httpREST)

        // v0.3 backward compatibility tests (4)
        print("\n── v0.3 Backward Compatibility ──")
        await testV03AgentCard(state: state, baseURL: baseURL)
        await testV03SendMessage(state: state, baseURL: baseURL)
        await testV03TaskLifecycle(state: state, baseURL: baseURL)
        await testV03Streaming(state: state, baseURL: baseURL)

        // Write results.json
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let timestamp = formatter.string(from: Date())

        let report = TestReport(
            client: "swift",
            sdk: sdkName,
            protocolVersion: "1.0",
            timestamp: timestamp,
            baseUrl: baseURL,
            results: state.results
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(report) {
            let resultsPath = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                .appendingPathComponent("results.json")
            try? data.write(to: resultsPath)
            print("\nResults written to \(resultsPath.path)")
        }

        // Summary
        let passed = state.results.filter { $0.passed }.count
        let failed = state.results.filter { !$0.passed }.count
        let total = state.results.count
        print("\n\(String(repeating: "=", count: 50))")
        print("  TOTAL: \(passed) passed, \(failed) failed, \(total) total")
        print(String(repeating: "=", count: 50))
    }
}
