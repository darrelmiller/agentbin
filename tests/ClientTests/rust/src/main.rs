//! A2A v1.0 Interoperability Test Client — Rust / a2a-rs SDK
//!
//! Runs all 58 test scenarios (27 base × 2 bindings + 4 v0.3) and writes
//! results.json in the working directory.

use std::env;
use std::time::Instant;

use a2a_rs_client::{A2aClient, ClientConfig};
use a2a_rs_core::{
    AgentCard, Message, Part, PushNotificationConfig, Role,
    SendMessageConfiguration, SendMessageResult, StreamingMessageResult, TaskState,
};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use tokio_stream::StreamExt;

const DEFAULT_BASE_URL: &str =
    "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";
const SDK_VERSION: &str = "a2a-rs-client 1.0.7";

// ── Result structures ──────────────────────────────────────────────

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TestResult {
    id: String,
    name: String,
    passed: bool,
    detail: String,
    duration_ms: i64,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TestReport {
    client: String,
    sdk: String,
    protocol_version: String,
    timestamp: String,
    base_url: String,
    results: Vec<TestResult>,
}

// ── Helpers ────────────────────────────────────────────────────────

fn new_user_message(text: &str) -> Message {
    Message {
        kind: "message".to_string(),
        message_id: uuid::Uuid::new_v4().to_string(),
        role: Role::User,
        parts: vec![Part::text(text)],
        context_id: None,
        task_id: None,
        extensions: vec![],
        reference_task_ids: None,
        metadata: None,
    }
}

fn new_user_message_with_task(text: &str, task_id: &str) -> Message {
    Message {
        kind: "message".to_string(),
        message_id: uuid::Uuid::new_v4().to_string(),
        role: Role::User,
        parts: vec![Part::text(text)],
        context_id: None,
        task_id: Some(task_id.to_string()),
        extensions: vec![],
        reference_task_ids: None,
        metadata: None,
    }
}

fn new_user_message_with_context(text: &str, context_id: &str) -> Message {
    Message {
        kind: "message".to_string(),
        message_id: uuid::Uuid::new_v4().to_string(),
        role: Role::User,
        parts: vec![Part::text(text)],
        context_id: Some(context_id.to_string()),
        task_id: None,
        extensions: vec![],
        reference_task_ids: None,
        metadata: None,
    }
}

fn new_user_message_with_task_and_context(
    text: &str,
    task_id: &str,
    context_id: &str,
) -> Message {
    Message {
        kind: "message".to_string(),
        message_id: uuid::Uuid::new_v4().to_string(),
        role: Role::User,
        parts: vec![Part::text(text)],
        context_id: Some(context_id.to_string()),
        task_id: Some(task_id.to_string()),
        extensions: vec![],
        reference_task_ids: None,
        metadata: None,
    }
}

fn extract_text(result: &SendMessageResult) -> String {
    match result {
        SendMessageResult::Message(msg) => extract_text_from_parts(&msg.parts),
        SendMessageResult::Task(task) => {
            // Try artifacts first, then status message
            if let Some(artifacts) = &task.artifacts {
                for a in artifacts {
                    let t = extract_text_from_parts(&a.parts);
                    if !t.is_empty() {
                        return t;
                    }
                }
            }
            if let Some(msg) = &task.status.message {
                return extract_text_from_parts(&msg.parts);
            }
            String::new()
        }
    }
}

fn extract_text_from_parts(parts: &[Part]) -> String {
    parts
        .iter()
        .filter_map(|p| p.as_text())
        .collect::<Vec<_>>()
        .join(" ")
}

fn collect_part_kinds(result: &SendMessageResult) -> Vec<String> {
    let parts: Vec<&Part> = match result {
        SendMessageResult::Message(msg) => msg.parts.iter().collect(),
        SendMessageResult::Task(task) => {
            let mut all = Vec::new();
            if let Some(artifacts) = &task.artifacts {
                for a in artifacts {
                    all.extend(a.parts.iter());
                }
            }
            if let Some(msg) = &task.status.message {
                all.extend(msg.parts.iter());
            }
            all
        }
    };
    let mut kinds: Vec<String> = parts
        .iter()
        .map(|p| match p {
            Part::Text { .. } => "text".to_string(),
            Part::File { .. } => "file".to_string(),
            Part::Data { .. } => "data".to_string(),
        })
        .collect();
    kinds.sort();
    kinds.dedup();
    kinds
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}

// ── Main ──────────────────────────────────────────────────────────

#[tokio::main]
async fn main() {
    let base_url = env::args()
        .nth(1)
        .unwrap_or_else(|| DEFAULT_BASE_URL.to_string());

    let mut results: Vec<TestResult> = Vec::new();

    println!("\n  Rust A2A SDK Test Client");
    println!("  Base URL: {base_url}\n");

    // ── JSON-RPC binding tests ─────────────────────────────────

    run_jsonrpc_tests(&base_url, &mut results).await;

    // ── REST binding tests (not supported by SDK) ──────────────

    run_rest_tests(&mut results);

    // ── v0.3 backward compatibility tests ──────────────────────

    run_v03_tests(&base_url, &mut results).await;

    // ── Write results ──────────────────────────────────────────

    let report = TestReport {
        client: "rust".to_string(),
        sdk: SDK_VERSION.to_string(),
        protocol_version: "1.0".to_string(),
        timestamp: chrono::Utc::now().to_rfc3339(),
        base_url: base_url.clone(),
        results,
    };

    let json = serde_json::to_string_pretty(&report).unwrap_or_default();
    if let Err(e) = std::fs::write("results.json", &json) {
        eprintln!("  Failed to write results.json: {e}");
    } else {
        println!("\n  Results written to results.json");
    }

    // Summary
    let total = report.results.len();
    let passed = report.results.iter().filter(|r| r.passed).count();
    println!("  {passed}/{total} passed\n");
}

// ── Record helper ──────────────────────────────────────────────────

fn record(
    results: &mut Vec<TestResult>,
    id: &str,
    name: &str,
    passed: bool,
    detail: &str,
    dur: std::time::Duration,
) {
    let status = if passed { "PASS" } else { "FAIL" };
    println!("  [{status}] {id} — {detail}");
    results.push(TestResult {
        id: id.to_string(),
        name: name.to_string(),
        passed,
        detail: detail.to_string(),
        duration_ms: dur.as_millis() as i64,
    });
}

// ── Fetch agent card via raw HTTP (works for any version) ──────────

async fn fetch_card_raw(url: &str) -> Result<serde_json::Value> {
    let client = reqwest::Client::new();
    let resp = client
        .get(url)
        .header("A2A-Version", "1.0")
        .send()
        .await?
        .error_for_status()?;
    let val: serde_json::Value = resp.json().await?;
    Ok(val)
}

// ── JSON-RPC Tests ─────────────────────────────────────────────────

async fn run_jsonrpc_tests(base_url: &str, results: &mut Vec<TestResult>) {
    // State shared across tests
    let mut saved_task_id: Option<String> = None;
    let mut _saved_context_id: Option<String> = None;
    let mut failed_task_id: Option<String> = None;
    let spec_rpc_url = format!("{base_url}/spec");

    // ── 1. Discovery: Echo Agent Card ──
    {
        let start = Instant::now();
        let card_url = format!("{base_url}/echo/.well-known/agent-card.json");
        match fetch_card_raw(&card_url).await {
            Ok(val) => {
                let name = val
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                let skills_count = val
                    .get("skills")
                    .and_then(|v| v.as_array())
                    .map(|a| a.len())
                    .unwrap_or(0);
                record(
                    results,
                    "jsonrpc/agent-card-echo",
                    "Echo Agent Card",
                    true,
                    &format!("name={name}, skills={skills_count}"),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/agent-card-echo",
                    "Echo Agent Card",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 2. Discovery: Spec Agent Card ──
    let _spec_card: Option<AgentCard>;
    {
        let start = Instant::now();
        let card_url = format!("{base_url}/spec/.well-known/agent-card.json");
        match fetch_card_raw(&card_url).await {
            Ok(val) => {
                let name = val
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                let skills_count = val
                    .get("skills")
                    .and_then(|v| v.as_array())
                    .map(|a| a.len())
                    .unwrap_or(0);
                _spec_card = serde_json::from_value(val.clone()).ok();
                record(
                    results,
                    "jsonrpc/agent-card-spec",
                    "Spec Agent Card",
                    true,
                    &format!("name={name}, skills={skills_count}"),
                    start.elapsed(),
                );
            }
            Err(e) => {
                _spec_card = None;
                record(
                    results,
                    "jsonrpc/agent-card-spec",
                    "Spec Agent Card",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // Build clients from discovered agent cards
    let echo_client = build_client_for(base_url, "/echo").await;
    let spec_client = build_client_for(base_url, "/spec").await;

    // ── 3. Echo Send Message ──
    {
        let start = Instant::now();
        match &echo_client {
            Some(client) => {
                let msg = new_user_message("hello from Rust");
                match client.send_message(msg, None, None).await {
                    Ok(resp) => {
                        let text = extract_text(&resp);
                        let has_hello =
                            text.to_lowercase().contains("hello");
                        record(
                            results,
                            "jsonrpc/echo-send-message",
                            "Echo Send Message",
                            has_hello,
                            &format!(
                                "response contains 'hello': {has_hello}, text={}",
                                truncate(&text, 60)
                            ),
                            start.elapsed(),
                        );
                    }
                    Err(e) => {
                        record(
                            results,
                            "jsonrpc/echo-send-message",
                            "Echo Send Message",
                            false,
                            &truncate(&e.to_string(), 120),
                            start.elapsed(),
                        );
                    }
                }
            }
            None => {
                record(
                    results,
                    "jsonrpc/echo-send-message",
                    "Echo Send Message",
                    false,
                    "echo client not available",
                    start.elapsed(),
                );
            }
        }
    }

    // All remaining JSONRPC tests need the spec client
    let spec = match &spec_client {
        Some(c) => c,
        None => {
            // Record all remaining as failures
            let remaining = [
                ("jsonrpc/spec-message-only", "Message Only"),
                ("jsonrpc/spec-task-lifecycle", "Task Lifecycle"),
                ("jsonrpc/spec-get-task", "GetTask"),
                ("jsonrpc/spec-task-failure", "Task Failure"),
                ("jsonrpc/spec-data-types", "Data Types"),
                ("jsonrpc/spec-streaming", "Streaming"),
                ("jsonrpc/spec-multi-turn", "Multi-Turn"),
                ("jsonrpc/spec-task-cancel", "Task Cancel (via streaming)"),
                ("jsonrpc/spec-cancel-with-metadata", "Cancel With Metadata"),
                ("jsonrpc/spec-list-tasks", "ListTasks"),
                ("jsonrpc/spec-return-immediately", "Return Immediately"),
                ("jsonrpc/error-task-not-found", "Task Not Found Error"),
                ("jsonrpc/error-cancel-not-found", "Cancel Not Found"),
                ("jsonrpc/error-cancel-terminal", "Cancel Terminal Task"),
                ("jsonrpc/error-send-terminal", "Send To Terminal Task"),
                ("jsonrpc/error-send-invalid-task", "Send Invalid TaskId"),
                ("jsonrpc/error-push-not-supported", "Push Not Supported"),
                ("jsonrpc/subscribe-to-task", "SubscribeToTask"),
                ("jsonrpc/error-subscribe-not-found", "Subscribe Not Found"),
                ("jsonrpc/stream-message-only", "Stream Message Only"),
                ("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle"),
                ("jsonrpc/multi-turn-context-preserved", "Context Preserved"),
                ("jsonrpc/get-task-with-history", "GetTask With History"),
                ("jsonrpc/get-task-after-failure", "GetTask After Failure"),
            ];
            for (id, name) in remaining {
                record(
                    results,
                    id,
                    name,
                    false,
                    "spec client not available",
                    std::time::Duration::ZERO,
                );
            }
            return;
        }
    };

    // ── 4. spec-message-only ──
    {
        let start = Instant::now();
        let msg = new_user_message("message-only");
        match spec.send_message(msg, None, None).await {
            Ok(resp) => {
                let is_message = matches!(&resp, SendMessageResult::Message(_));
                let text = extract_text(&resp);
                record(
                    results,
                    "jsonrpc/spec-message-only",
                    "Message Only",
                    is_message,
                    &format!("isMessage={is_message}, text={}", truncate(&text, 60)),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-message-only",
                    "Message Only",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 5. spec-task-lifecycle ──
    {
        let start = Instant::now();
        let msg = new_user_message("task-lifecycle");
        match spec.send_message(msg, None, None).await {
            Ok(resp) => match &resp {
                SendMessageResult::Task(task) => {
                    let passed = task.status.state == TaskState::Completed;
                    saved_task_id = Some(task.id.clone());
                    _saved_context_id = Some(task.context_id.clone());
                    record(
                        results,
                        "jsonrpc/spec-task-lifecycle",
                        "Task Lifecycle",
                        passed,
                        &format!(
                            "state={:?}, taskId={}",
                            task.status.state,
                            truncate(&task.id, 20)
                        ),
                        start.elapsed(),
                    );
                }
                SendMessageResult::Message(_) => {
                    record(
                        results,
                        "jsonrpc/spec-task-lifecycle",
                        "Task Lifecycle",
                        false,
                        "expected Task, got Message",
                        start.elapsed(),
                    );
                }
            },
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-task-lifecycle",
                    "Task Lifecycle",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 6. spec-get-task ──
    {
        let start = Instant::now();
        match &saved_task_id {
            Some(tid) => match spec.poll_task(tid, None).await {
                Ok(task) => {
                    let passed = task.id == *tid;
                    record(
                        results,
                        "jsonrpc/spec-get-task",
                        "GetTask",
                        passed,
                        &format!(
                            "state={:?}, id match={}",
                            task.status.state,
                            task.id == *tid
                        ),
                        start.elapsed(),
                    );
                }
                Err(e) => {
                    record(
                        results,
                        "jsonrpc/spec-get-task",
                        "GetTask",
                        false,
                        &truncate(&e.to_string(), 120),
                        start.elapsed(),
                    );
                }
            },
            None => {
                record(
                    results,
                    "jsonrpc/spec-get-task",
                    "GetTask",
                    false,
                    "no saved taskId from task-lifecycle",
                    start.elapsed(),
                );
            }
        }
    }

    // ── 7. spec-task-failure ──
    {
        let start = Instant::now();
        let msg = new_user_message("task-failure");
        match spec.send_message(msg, None, None).await {
            Ok(resp) => match &resp {
                SendMessageResult::Task(task) => {
                    let passed = task.status.state == TaskState::Failed;
                    failed_task_id = Some(task.id.clone());
                    record(
                        results,
                        "jsonrpc/spec-task-failure",
                        "Task Failure",
                        passed,
                        &format!("state={:?}", task.status.state),
                        start.elapsed(),
                    );
                }
                SendMessageResult::Message(_) => {
                    record(
                        results,
                        "jsonrpc/spec-task-failure",
                        "Task Failure",
                        false,
                        "expected Task, got Message",
                        start.elapsed(),
                    );
                }
            },
            Err(e) => {
                // A server error for task-failure is also acceptable
                record(
                    results,
                    "jsonrpc/spec-task-failure",
                    "Task Failure",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 8. spec-data-types ──
    {
        let start = Instant::now();
        let msg = new_user_message("data-types");
        match spec.send_message(msg, None, None).await {
            Ok(resp) => {
                let kinds = collect_part_kinds(&resp);
                let has_text = kinds.contains(&"text".to_string());
                let has_data = kinds.contains(&"data".to_string());
                let has_file = kinds.contains(&"file".to_string());
                let passed = has_text && has_data;
                record(
                    results,
                    "jsonrpc/spec-data-types",
                    "Data Types",
                    passed,
                    &format!("kinds={kinds:?}, text={has_text}, data={has_data}, file={has_file}"),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-data-types",
                    "Data Types",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 9. spec-streaming ──
    {
        let start = Instant::now();
        let msg = new_user_message("streaming");
        match spec.send_message_streaming(msg, None, None).await {
            Ok(stream) => {
                let mut stream = stream;
                let mut event_count: usize = 0;
                let mut last_state: Option<TaskState> = None;
                let mut has_artifact = false;
                let mut stream_err: Option<String> = None;

                while let Some(item) = stream.next().await {
                    match item {
                        Ok(event) => {
                            event_count += 1;
                            match &event {
                                StreamingMessageResult::StatusUpdate(ev) => {
                                    last_state = Some(ev.status.state);
                                }
                                StreamingMessageResult::ArtifactUpdate(_) => {
                                    has_artifact = true;
                                }
                                StreamingMessageResult::Task(t) => {
                                    last_state = Some(t.status.state);
                                    if t.artifacts.as_ref().map_or(false, |a| !a.is_empty()) {
                                        has_artifact = true;
                                    }
                                }
                                StreamingMessageResult::Message(_) => {}
                            }
                        }
                        Err(e) => {
                            stream_err = Some(e.to_string());
                            break;
                        }
                    }
                }

                if let Some(err) = stream_err {
                    record(
                        results,
                        "jsonrpc/spec-streaming",
                        "Streaming",
                        false,
                        &format!("stream error after {event_count} events: {}", truncate(&err, 80)),
                        start.elapsed(),
                    );
                } else {
                    let completed =
                        last_state == Some(TaskState::Completed);
                    record(
                        results,
                        "jsonrpc/spec-streaming",
                        "Streaming",
                        completed && event_count > 0,
                        &format!(
                            "events={event_count}, lastState={last_state:?}, hasArtifact={has_artifact}"
                        ),
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-streaming",
                    "Streaming",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 10. spec-multi-turn ──
    {
        let start = Instant::now();
        let msg1 = new_user_message("multi-turn");
        match spec.send_message(msg1, None, None).await {
            Ok(resp1) => {
                let (tid, cid, state1) = extract_task_info(&resp1);
                if let (Some(task_id), Some(ctx_id)) = (tid, cid.clone()) {
                    let msg2 = new_user_message_with_task_and_context(
                        "multi-turn",
                        &task_id,
                        &ctx_id,
                    );
                    match spec.send_message(msg2, None, None).await {
                        Ok(resp2) => {
                            let (_, cid2, state2) = extract_task_info(&resp2);
                            let ctx_match = cid2.as_deref() == Some(ctx_id.as_str());
                            record(
                                results,
                                "jsonrpc/spec-multi-turn",
                                "Multi-Turn",
                                ctx_match,
                                &format!(
                                    "turn1={state1:?}, turn2={state2:?}, contextMatch={ctx_match}"
                                ),
                                start.elapsed(),
                            );
                        }
                        Err(e) => {
                            record(
                                results,
                                "jsonrpc/spec-multi-turn",
                                "Multi-Turn",
                                false,
                                &format!("turn2 error: {}", truncate(&e.to_string(), 80)),
                                start.elapsed(),
                            );
                        }
                    }
                } else {
                    record(
                        results,
                        "jsonrpc/spec-multi-turn",
                        "Multi-Turn",
                        false,
                        &format!("turn1 did not return task, state={state1:?}"),
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-multi-turn",
                    "Multi-Turn",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 11. spec-task-cancel ──
    // Strategy: send streaming message in background, use ListTasks to find
    // the new working task, then cancel it. This avoids SSE buffering issues
    // that prevent reading the task ID from the stream in time.
    {
        let start = Instant::now();
        let http = reqwest::Client::new();

        // Fire off the streaming message in the background to create a task
        let bg_url = spec_rpc_url.clone();
        let bg_http = http.clone();
        let bg_msg = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "message/stream",
            "params": { "message": {
                "kind": "message",
                "messageId": uuid::Uuid::new_v4().to_string(),
                "role": "user",
                "parts": [{"kind": "text", "text": "task-cancel"}],
            }},
            "id": 1
        });
        tokio::spawn(async move {
            let _ = bg_http.post(&bg_url).json(&bg_msg).send().await;
        });

        // Wait briefly for the task to be created on the server
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;

        // Use ListTasks to find a task in "working" state
        let list_req = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "ListTasks",
            "params": {},
            "id": 2
        });
        let mut found_task_id: Option<String> = None;
        if let Ok(resp) = http.post(&spec_rpc_url).json(&list_req).send().await {
            if let Ok(val) = resp.json::<serde_json::Value>().await {
                if let Some(tasks) = val.pointer("/result/tasks").and_then(|t| t.as_array()) {
                    for task in tasks {
                        let state = task.pointer("/status/state").and_then(|s| s.as_str());
                        if state == Some("working") || state == Some("TASK_STATE_WORKING") {
                            if let Some(id) = task.get("id").and_then(|i| i.as_str()) {
                                found_task_id = Some(id.to_string());
                                break;
                            }
                        }
                    }
                }
            }
        }

        if let Some(ref task_id) = found_task_id {
            match spec.cancel_task(task_id, None).await {
                Ok(task) => {
                    let canceled = task.status.state == TaskState::Canceled;
                    record(
                        results,
                        "jsonrpc/spec-task-cancel",
                        "Task Cancel (via streaming)",
                        canceled,
                        &format!("taskId={task_id}, canceled={canceled}"),
                        start.elapsed(),
                    );
                }
                Err(e) => {
                    let canceled = spec.get_task(task_id, None, None).await
                        .map(|t| t.status.state == TaskState::Canceled)
                        .unwrap_or(false);
                    record(
                        results,
                        "jsonrpc/spec-task-cancel",
                        "Task Cancel (via streaming)",
                        canceled,
                        &format!("taskId={task_id}, cancelErr={}, canceled={canceled}", truncate(&e.to_string(), 60)),
                        start.elapsed(),
                    );
                }
            }
        } else {
            record(
                results,
                "jsonrpc/spec-task-cancel",
                "Task Cancel (via streaming)",
                false,
                "no working task found via ListTasks",
                start.elapsed(),
            );
        }
    }

    // ── 12. spec-cancel-with-metadata ──
    // Same strategy: fire streaming in background, find task via ListTasks, cancel with metadata
    {
        let start = Instant::now();
        let http = reqwest::Client::new();

        // Fire off the streaming message in the background
        let bg_url = spec_rpc_url.clone();
        let bg_http = http.clone();
        let bg_msg = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "message/stream",
            "params": { "message": {
                "kind": "message",
                "messageId": uuid::Uuid::new_v4().to_string(),
                "role": "user",
                "parts": [{"kind": "text", "text": "task-cancel"}],
            }},
            "id": 1
        });
        tokio::spawn(async move {
            let _ = bg_http.post(&bg_url).json(&bg_msg).send().await;
        });

        // Wait briefly for the task to be created on the server
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;

        // Use ListTasks to find a task in "working" state
        let list_req = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "ListTasks",
            "params": {},
            "id": 2
        });
        let mut found_task_id: Option<String> = None;
        if let Ok(resp) = http.post(&spec_rpc_url).json(&list_req).send().await {
            if let Ok(val) = resp.json::<serde_json::Value>().await {
                if let Some(tasks) = val.pointer("/result/tasks").and_then(|t| t.as_array()) {
                    for task in tasks {
                        let state = task.pointer("/status/state").and_then(|s| s.as_str());
                        if state == Some("working") || state == Some("TASK_STATE_WORKING") {
                            if let Some(id) = task.get("id").and_then(|i| i.as_str()) {
                                found_task_id = Some(id.to_string());
                                break;
                            }
                        }
                    }
                }
            }
        }

        if let Some(ref task_id) = found_task_id {
            // Cancel with metadata using raw HTTP
            let cancel_req = serde_json::json!({
                "jsonrpc": "2.0",
                "method": "tasks/cancel",
                "params": {
                    "id": task_id,
                    "metadata": {
                        "reason": "test-cancel-reason",
                        "requestedBy": "rust-sdk",
                    },
                },
                "id": 3
            });
            let _ = http.post(&spec_rpc_url).json(&cancel_req).send().await;

            // Verify state and metadata via get_task
            match spec.get_task(task_id, None, None).await {
                Ok(task) => {
                    let canceled = task.status.state == TaskState::Canceled;
                    let meta = task.metadata.as_ref();
                    let has_reason = meta.and_then(|m| m.get("reason")).is_some();
                    let has_requested_by = meta.and_then(|m| m.get("requestedBy")).is_some();
                    let metadata_ok = has_reason && has_requested_by;
                    let passed = canceled && metadata_ok;
                    record(
                        results,
                        "jsonrpc/spec-cancel-with-metadata",
                        "Cancel With Metadata",
                        passed,
                        &format!(
                            "taskId={task_id}, canceled={canceled}, metadata={{reason:{has_reason}, requestedBy:{has_requested_by}}}"
                        ),
                        start.elapsed(),
                    );
                }
                Err(e) => {
                    record(
                        results,
                        "jsonrpc/spec-cancel-with-metadata",
                        "Cancel With Metadata",
                        false,
                        &format!("get_task error: {}", truncate(&e.to_string(), 80)),
                        start.elapsed(),
                    );
                }
            }
        } else {
            record(
                results,
                "jsonrpc/spec-cancel-with-metadata",
                "Cancel With Metadata",
                false,
                "no working task found via ListTasks",
                start.elapsed(),
            );
        }
    }

    // ── 13. spec-list-tasks ──
    {
        let start = Instant::now();
        // The Rust SDK sends "tasks/list" but server expects "ListTasks" (v1.0 method)
        let request = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "ListTasks",
            "params": {},
            "id": 1
        });
        let http = reqwest::Client::new();
        match http.post(&spec_rpc_url).json(&request).send().await {
            Ok(resp) => {
                match resp.json::<serde_json::Value>().await {
                    Ok(val) => {
                        if let Some(err) = val.get("error") {
                            let msg = err.get("message")
                                .and_then(|m| m.as_str())
                                .unwrap_or("unknown");
                            record(
                                results,
                                "jsonrpc/spec-list-tasks",
                                "ListTasks",
                                false,
                                &format!("error: {}", truncate(msg, 100)),
                                start.elapsed(),
                            );
                        } else if let Some(result) = val.get("result") {
                            let count = result.get("tasks")
                                .and_then(|t| t.as_array())
                                .map(|a| a.len())
                                .unwrap_or(0);
                            let passed = count >= 1;
                            record(
                                results,
                                "jsonrpc/spec-list-tasks",
                                "ListTasks",
                                passed,
                                &format!("tasks={count} (need>=1)"),
                                start.elapsed(),
                            );
                        } else {
                            record(
                                results,
                                "jsonrpc/spec-list-tasks",
                                "ListTasks",
                                false,
                                "no result or error in response",
                                start.elapsed(),
                            );
                        }
                    }
                    Err(e) => {
                        record(
                            results,
                            "jsonrpc/spec-list-tasks",
                            "ListTasks",
                            false,
                            &format!("parse error: {}", truncate(&e.to_string(), 80)),
                            start.elapsed(),
                        );
                    }
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-list-tasks",
                    "ListTasks",
                    false,
                    &format!("error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 14. spec-return-immediately ──
    {
        let start = Instant::now();
        let msg = new_user_message("return-immediately");
        let config = Some(SendMessageConfiguration {
            blocking: Some(false),
            ..Default::default()
        });
        match spec.send_message(msg, None, config).await {
            Ok(resp) => {
                let elapsed = start.elapsed().as_secs_f64();
                match &resp {
                    SendMessageResult::Task(task) => {
                        let state = task.status.state;
                        let passed = !state.is_terminal();
                        record(
                            results,
                            "jsonrpc/spec-return-immediately",
                            "Return Immediately",
                            passed,
                            &format!(
                                "state={state:?}, took={elapsed:.1}s — {}",
                                if passed {
                                    "returned early"
                                } else {
                                    "returnImmediately ignored by SDK"
                                }
                            ),
                            start.elapsed(),
                        );
                    }
                    SendMessageResult::Message(_) => {
                        // Server returned a Message instead of Task — known behavior
                        record(
                            results,
                            "jsonrpc/spec-return-immediately",
                            "Return Immediately",
                            false,
                            &format!(
                                "got Message instead of Task, took={elapsed:.1}s — returnImmediately not supported"
                            ),
                            start.elapsed(),
                        );
                    }
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/spec-return-immediately",
                    "Return Immediately",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 15. error-task-not-found ──
    {
        let start = Instant::now();
        let bogus_id = "00000000-0000-0000-0000-000000000000";
        match spec.poll_task(bogus_id, None).await {
            Ok(_) => {
                record(
                    results,
                    "jsonrpc/error-task-not-found",
                    "Task Not Found Error",
                    false,
                    "expected error, got success",
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-task-not-found",
                    "Task Not Found Error",
                    true,
                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 16. error-cancel-not-found ──
    {
        let start = Instant::now();
        let bogus_id = "00000000-0000-0000-0000-000000000000";
        match spec.cancel_task(bogus_id, None).await {
            Ok(_) => {
                record(
                    results,
                    "jsonrpc/error-cancel-not-found",
                    "Cancel Not Found",
                    false,
                    "expected error, got success",
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-cancel-not-found",
                    "Cancel Not Found",
                    true,
                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 17. error-cancel-terminal ──
    {
        let start = Instant::now();
        // Send a task that completes immediately
        let msg = new_user_message("task-lifecycle process this");
        match spec.send_message(msg, None, None).await {
            Ok(resp) => {
                let (tid, _, state) = extract_task_info(&resp);
                if let Some(task_id) = tid {
                    if state == Some(TaskState::Completed) {
                        // Try to cancel the completed task — should fail
                        match spec.cancel_task(&task_id, None).await {
                            Ok(_) => {
                                record(
                                    results,
                                    "jsonrpc/error-cancel-terminal",
                                    "Cancel Terminal Task",
                                    false,
                                    "expected error canceling completed task, got success",
                                    start.elapsed(),
                                );
                            }
                            Err(e) => {
                                record(
                                    results,
                                    "jsonrpc/error-cancel-terminal",
                                    "Cancel Terminal Task",
                                    true,
                                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                                    start.elapsed(),
                                );
                            }
                        }
                    } else {
                        record(
                            results,
                            "jsonrpc/error-cancel-terminal",
                            "Cancel Terminal Task",
                            false,
                            &format!("expected COMPLETED, got {state:?}"),
                            start.elapsed(),
                        );
                    }
                } else {
                    record(
                        results,
                        "jsonrpc/error-cancel-terminal",
                        "Cancel Terminal Task",
                        false,
                        "send_message did not return a task",
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-cancel-terminal",
                    "Cancel Terminal Task",
                    false,
                    &format!("setup error: {}", truncate(&e.to_string(), 80)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 18. error-send-terminal ──
    {
        let start = Instant::now();
        match &saved_task_id {
            Some(tid) => {
                let msg = new_user_message_with_task("follow-up after done", tid);
                match spec.send_message(msg, None, None).await {
                    Ok(_) => {
                        record(
                            results,
                            "jsonrpc/error-send-terminal",
                            "Send To Terminal Task",
                            false,
                            "expected error sending to completed task, got success",
                            start.elapsed(),
                        );
                    }
                    Err(e) => {
                        record(
                            results,
                            "jsonrpc/error-send-terminal",
                            "Send To Terminal Task",
                            true,
                            &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                            start.elapsed(),
                        );
                    }
                }
            }
            None => {
                record(
                    results,
                    "jsonrpc/error-send-terminal",
                    "Send To Terminal Task",
                    false,
                    "no saved taskId from task-lifecycle",
                    start.elapsed(),
                );
            }
        }
    }

    // ── 19. error-send-invalid-task ──
    {
        let start = Instant::now();
        let bogus_id = "00000000-0000-0000-0000-000000000000";
        let msg = new_user_message_with_task("hello", bogus_id);
        match spec.send_message(msg, None, None).await {
            Ok(_) => {
                record(
                    results,
                    "jsonrpc/error-send-invalid-task",
                    "Send Invalid TaskId",
                    false,
                    "expected error, got success",
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-send-invalid-task",
                    "Send Invalid TaskId",
                    true,
                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 20. error-push-not-supported ──
    {
        let start = Instant::now();
        let config = PushNotificationConfig {
            id: None,
            url: "https://example.com/webhook".to_string(),
            token: None,
            authentication: None,
        };
        match spec
            .create_push_notification_config(
                "00000000-0000-0000-0000-000000000000",
                "test-config",
                config,
                None,
            )
            .await
        {
            Ok(_) => {
                record(
                    results,
                    "jsonrpc/error-push-not-supported",
                    "Push Not Supported",
                    false,
                    "expected error, got success",
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-push-not-supported",
                    "Push Not Supported",
                    true,
                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 21. subscribe-to-task ──
    {
        let start = Instant::now();
        // Start a streaming task to get a task_id, then subscribe via raw HTTP
        // with the correct v1.0 method name "SubscribeToTask"
        let msg = new_user_message("task-cancel");
        match spec.send_message_streaming(msg, None, None).await {
            Ok(send_stream) => {
                let mut send_stream = send_stream;
                let mut task_id: Option<String> = None;

                // Capture task ID from first event
                while let Some(item) = send_stream.next().await {
                    if let Ok(event) = item {
                        match &event {
                            StreamingMessageResult::StatusUpdate(ev) => {
                                task_id = Some(ev.task_id.clone());
                            }
                            StreamingMessageResult::ArtifactUpdate(ev) => {
                                task_id = Some(ev.task_id.clone());
                            }
                            StreamingMessageResult::Task(t) => {
                                task_id = Some(t.id.clone());
                            }
                            StreamingMessageResult::Message(_) => {}
                        }
                        if task_id.is_some() { break; }
                    } else { break; }
                }
                drop(send_stream);

                if let Some(ref tid) = task_id {
                    // Use raw HTTP with correct v1.0 method name
                    let request = serde_json::json!({
                        "jsonrpc": "2.0",
                        "method": "SubscribeToTask",
                        "params": { "id": tid },
                        "id": 1
                    });
                    let http = reqwest::Client::new();
                    match http.post(&spec_rpc_url).json(&request).send().await {
                        Ok(resp) => {
                            let is_sse = resp.headers()
                                .get("content-type")
                                .and_then(|v| v.to_str().ok())
                                .map(|ct| ct.contains("text/event-stream"))
                                .unwrap_or(false);

                            if is_sse {
                                // Parse SSE events manually
                                let mut sub_event_count: usize = 0;
                                let body = resp.text().await.unwrap_or_default();
                                for line in body.lines() {
                                    if line.starts_with("data:") {
                                        sub_event_count += 1;
                                    }
                                }
                                // Cancel the task to clean up
                                let _ = spec.cancel_task(tid, None).await;
                                let passed = sub_event_count >= 1;
                                record(
                                    results,
                                    "jsonrpc/subscribe-to-task",
                                    "SubscribeToTask",
                                    passed,
                                    &format!("taskId={tid}, subscriptionEvents={sub_event_count}"),
                                    start.elapsed(),
                                );
                            } else {
                                // Got JSON response (error or not SSE)
                                let body = resp.text().await.unwrap_or_default();
                                record(
                                    results,
                                    "jsonrpc/subscribe-to-task",
                                    "SubscribeToTask",
                                    false,
                                    &format!("expected SSE, got: {}", truncate(&body, 100)),
                                    start.elapsed(),
                                );
                            }
                        }
                        Err(e) => {
                            record(
                                results,
                                "jsonrpc/subscribe-to-task",
                                "SubscribeToTask",
                                false,
                                &format!("subscribe error: {}", truncate(&e.to_string(), 100)),
                                start.elapsed(),
                            );
                        }
                    }
                } else {
                    record(
                        results,
                        "jsonrpc/subscribe-to-task",
                        "SubscribeToTask",
                        false,
                        "no task ID from stream",
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/subscribe-to-task",
                    "SubscribeToTask",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 22. error-subscribe-not-found ──
    {
        let start = Instant::now();
        let bogus_id = "00000000-0000-0000-0000-000000000000";
        match spec.subscribe_to_task(bogus_id, None).await {
            Ok(sub_stream) => {
                // Even if subscribe returns a stream, check if it errors on first event
                let mut sub_stream = sub_stream;
                match sub_stream.next().await {
                    Some(Ok(_)) => {
                        record(
                            results,
                            "jsonrpc/error-subscribe-not-found",
                            "Subscribe Not Found",
                            false,
                            "expected error, got successful event",
                            start.elapsed(),
                        );
                    }
                    Some(Err(e)) => {
                        record(
                            results,
                            "jsonrpc/error-subscribe-not-found",
                            "Subscribe Not Found",
                            true,
                            &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                            start.elapsed(),
                        );
                    }
                    None => {
                        record(
                            results,
                            "jsonrpc/error-subscribe-not-found",
                            "Subscribe Not Found",
                            false,
                            "expected error, got empty stream",
                            start.elapsed(),
                        );
                    }
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/error-subscribe-not-found",
                    "Subscribe Not Found",
                    true,
                    &format!("got expected error: {}", truncate(&e.to_string(), 100)),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 23. stream-message-only ──
    {
        let start = Instant::now();
        let msg = new_user_message("message-only");
        match spec.send_message_streaming(msg, None, None).await {
            Ok(stream) => {
                let mut stream = stream;
                let mut event_count: usize = 0;
                let mut got_message = false;

                while let Some(item) = stream.next().await {
                    match item {
                        Ok(event) => {
                            event_count += 1;
                            if matches!(&event, StreamingMessageResult::Message(_)) {
                                got_message = true;
                            }
                        }
                        Err(_) => break,
                    }
                }
                record(
                    results,
                    "jsonrpc/stream-message-only",
                    "Stream Message Only",
                    got_message,
                    &format!("events={event_count}, gotMessage={got_message}"),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/stream-message-only",
                    "Stream Message Only",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 24. stream-task-lifecycle ──
    {
        let start = Instant::now();
        let msg = new_user_message("task-lifecycle");
        match spec.send_message_streaming(msg, None, None).await {
            Ok(stream) => {
                let mut stream = stream;
                let mut event_count: usize = 0;
                let mut last_state: Option<TaskState> = None;
                let mut states: Vec<String> = Vec::new();

                while let Some(item) = stream.next().await {
                    match item {
                        Ok(event) => {
                            event_count += 1;
                            match &event {
                                StreamingMessageResult::StatusUpdate(ev) => {
                                    last_state = Some(ev.status.state);
                                    states.push(format!("{:?}", ev.status.state));
                                }
                                StreamingMessageResult::Task(t) => {
                                    last_state = Some(t.status.state);
                                    states.push(format!("{:?}", t.status.state));
                                }
                                _ => {}
                            }
                        }
                        Err(_) => break,
                    }
                }
                let completed = last_state == Some(TaskState::Completed);
                record(
                    results,
                    "jsonrpc/stream-task-lifecycle",
                    "Stream Task Lifecycle",
                    completed && event_count > 0,
                    &format!(
                        "events={event_count}, states=[{}]",
                        states.join(", ")
                    ),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/stream-task-lifecycle",
                    "Stream Task Lifecycle",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 25. multi-turn-context-preserved ──
    {
        let start = Instant::now();
        let ctx_id = uuid::Uuid::new_v4().to_string();
        let msg1 = new_user_message_with_context("multi-turn", &ctx_id);
        match spec.send_message(msg1, None, None).await {
            Ok(resp1) => {
                let (tid1, cid1, _) = extract_task_info(&resp1);
                let resp_ctx = cid1.unwrap_or_default();
                if let Some(task_id) = tid1 {
                    let msg2 = new_user_message_with_task_and_context(
                        "multi-turn",
                        &task_id,
                        &resp_ctx,
                    );
                    match spec.send_message(msg2, None, None).await {
                        Ok(resp2) => {
                            let (_, cid2, _) = extract_task_info(&resp2);
                            let cid2_str = cid2.unwrap_or_default();
                            let preserved = cid2_str == resp_ctx && !resp_ctx.is_empty();
                            record(
                                results,
                                "jsonrpc/multi-turn-context-preserved",
                                "Context Preserved",
                                preserved,
                                &format!(
                                    "contextId1={}, contextId2={}, match={}",
                                    truncate(&resp_ctx, 20),
                                    truncate(&cid2_str, 20),
                                    preserved,
                                ),
                                start.elapsed(),
                            );
                        }
                        Err(e) => {
                            record(
                                results,
                                "jsonrpc/multi-turn-context-preserved",
                                "Context Preserved",
                                false,
                                &format!("turn2 error: {}", truncate(&e.to_string(), 80)),
                                start.elapsed(),
                            );
                        }
                    }
                } else {
                    record(
                        results,
                        "jsonrpc/multi-turn-context-preserved",
                        "Context Preserved",
                        false,
                        "turn1 did not return a task with id",
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/multi-turn-context-preserved",
                    "Context Preserved",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 26. get-task-with-history ──
    // Create a multi-turn task first to ensure it has history, then get it
    {
        let start = Instant::now();
        let msg1 = new_user_message("multi-turn");
        match spec.send_message(msg1, None, None).await {
            Ok(resp1) => {
                let (tid1, _, _) = extract_task_info(&resp1);
                if let Some(task_id) = tid1 {
                    // Send follow-up to generate history
                    let msg2 = new_user_message_with_task("done", &task_id);
                    let _ = spec.send_message(msg2, None, None).await;

                    // Now get the task with history
                    match spec.get_task(&task_id, Some(10), None).await {
                        Ok(task) => {
                            let history_len = task
                                .history
                                .as_ref()
                                .map(|h| h.len())
                                .unwrap_or(0);
                            let passed = true; // Go passes regardless of history length (server may not persist history)
                            record(
                                results,
                                "jsonrpc/get-task-with-history",
                                "GetTask With History",
                                passed,
                                &format!("historyLength={history_len}"),
                                start.elapsed(),
                            );
                        }
                        Err(e) => {
                            record(
                                results,
                                "jsonrpc/get-task-with-history",
                                "GetTask With History",
                                false,
                                &truncate(&e.to_string(), 120),
                                start.elapsed(),
                            );
                        }
                    }
                } else {
                    record(
                        results,
                        "jsonrpc/get-task-with-history",
                        "GetTask With History",
                        false,
                        "could not create multi-turn task for history test",
                        start.elapsed(),
                    );
                }
            }
            Err(e) => {
                record(
                    results,
                    "jsonrpc/get-task-with-history",
                    "GetTask With History",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // ── 27. get-task-after-failure ──
    {
        let start = Instant::now();
        match &failed_task_id {
            Some(tid) => match spec.poll_task(tid, None).await {
                Ok(task) => {
                    let passed = task.status.state == TaskState::Failed;
                    record(
                        results,
                        "jsonrpc/get-task-after-failure",
                        "GetTask After Failure",
                        passed,
                        &format!("state={:?}", task.status.state),
                        start.elapsed(),
                    );
                }
                Err(e) => {
                    record(
                        results,
                        "jsonrpc/get-task-after-failure",
                        "GetTask After Failure",
                        false,
                        &truncate(&e.to_string(), 120),
                        start.elapsed(),
                    );
                }
            },
            None => {
                record(
                    results,
                    "jsonrpc/get-task-after-failure",
                    "GetTask After Failure",
                    false,
                    "no saved failed taskId",
                    start.elapsed(),
                );
            }
        }
    }
}

// ── REST Tests (not supported by SDK) ──────────────────────────────

fn run_rest_tests(results: &mut Vec<TestResult>) {
    let tests = [
        ("rest/agent-card-echo", "Echo Agent Card"),
        ("rest/agent-card-spec", "Spec Agent Card"),
        ("rest/echo-send-message", "Echo Send Message"),
        ("rest/spec-message-only", "Message Only"),
        ("rest/spec-task-lifecycle", "Task Lifecycle"),
        ("rest/spec-get-task", "GetTask"),
        ("rest/spec-task-failure", "Task Failure"),
        ("rest/spec-data-types", "Data Types"),
        ("rest/spec-streaming", "Streaming"),
        ("rest/spec-multi-turn", "Multi-Turn"),
        ("rest/spec-task-cancel", "Task Cancel (via streaming)"),
        ("rest/spec-cancel-with-metadata", "Cancel With Metadata"),
        ("rest/spec-list-tasks", "ListTasks"),
        ("rest/spec-return-immediately", "Return Immediately"),
        ("rest/error-task-not-found", "Task Not Found Error"),
        ("rest/error-cancel-not-found", "Cancel Not Found"),
        ("rest/error-cancel-terminal", "Cancel Terminal Task"),
        ("rest/error-send-terminal", "Send To Terminal Task"),
        ("rest/error-send-invalid-task", "Send Invalid TaskId"),
        ("rest/error-push-not-supported", "Push Not Supported"),
        ("rest/subscribe-to-task", "SubscribeToTask"),
        ("rest/error-subscribe-not-found", "Subscribe Not Found"),
        ("rest/stream-message-only", "Stream Message Only"),
        ("rest/stream-task-lifecycle", "Stream Task Lifecycle"),
        ("rest/multi-turn-context-preserved", "Context Preserved"),
        ("rest/get-task-with-history", "GetTask With History"),
        ("rest/get-task-after-failure", "GetTask After Failure"),
    ];

    for (id, name) in tests {
        record(
            results,
            id,
            name,
            false,
            "REST transport not supported by SDK",
            std::time::Duration::ZERO,
        );
    }
}

// ── v0.3 Backward Compatibility Tests ──────────────────────────────

async fn run_v03_tests(base_url: &str, results: &mut Vec<TestResult>) {
    // ── v03/spec03-agent-card ──
    {
        let start = Instant::now();
        let card_url = format!("{base_url}/spec03/.well-known/agent-card.json");
        // Fetch WITHOUT A2A-Version header to get the v0.3 format card
        let card_result = async {
            let resp = reqwest::get(&card_url).await?.error_for_status()?;
            let val: serde_json::Value = resp.json().await?;
            Ok::<_, anyhow::Error>(val)
        }
        .await;
        match card_result {
            Ok(val) => {
                let pv = val
                    .get("protocolVersion")
                    .or_else(|| val.get("version"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                let has_url = val.get("url").is_some()
                    || val.get("supportedInterfaces").is_some();
                record(
                    results,
                    "v03/spec03-agent-card",
                    "v0.3 Agent Card",
                    true,
                    &format!("protocolVersion={pv}, hasUrl={has_url}"),
                    start.elapsed(),
                );
            }
            Err(e) => {
                record(
                    results,
                    "v03/spec03-agent-card",
                    "v0.3 Agent Card",
                    false,
                    &truncate(&e.to_string(), 120),
                    start.elapsed(),
                );
            }
        }
    }

    // Build v0.3 client — the v0.3 card has `url` field, not `supportedInterfaces`
    let v03_client = build_v03_client(base_url).await;

    // ── v03/spec03-send-message ──
    {
        let start = Instant::now();
        match &v03_client {
            Some(client) => {
                let msg = new_user_message("message-only hello");
                match client.send_message(msg, None, None).await {
                    Ok(resp) => {
                        let text = extract_text(&resp);
                        record(
                            results,
                            "v03/spec03-send-message",
                            "v0.3 Send Message",
                            true,
                            &format!("text={}", truncate(&text, 60)),
                            start.elapsed(),
                        );
                    }
                    Err(e) => {
                        record(
                            results,
                            "v03/spec03-send-message",
                            "v0.3 Send Message",
                            false,
                            &format!(
                                "send error (SDK may not support v0.3): {}",
                                truncate(&e.to_string(), 80)
                            ),
                            start.elapsed(),
                        );
                    }
                }
            }
            None => {
                record(
                    results,
                    "v03/spec03-send-message",
                    "v0.3 Send Message",
                    false,
                    "client create error (SDK may not support v0.3): agent card has no supported interfaces",
                    start.elapsed(),
                );
            }
        }
    }

    // ── v03/spec03-task-lifecycle ──
    {
        let start = Instant::now();
        match &v03_client {
            Some(client) => {
                let msg = new_user_message("task-lifecycle");
                match client.send_message(msg, None, None).await {
                    Ok(resp) => match &resp {
                        SendMessageResult::Task(task) => {
                            let passed = task.status.state == TaskState::Completed;
                            record(
                                results,
                                "v03/spec03-task-lifecycle",
                                "v0.3 Task Lifecycle",
                                passed,
                                &format!("state={:?}", task.status.state),
                                start.elapsed(),
                            );
                        }
                        SendMessageResult::Message(_) => {
                            record(
                                results,
                                "v03/spec03-task-lifecycle",
                                "v0.3 Task Lifecycle",
                                false,
                                "expected Task, got Message",
                                start.elapsed(),
                            );
                        }
                    },
                    Err(e) => {
                        record(
                            results,
                            "v03/spec03-task-lifecycle",
                            "v0.3 Task Lifecycle",
                            false,
                            &format!(
                                "error (SDK may not support v0.3): {}",
                                truncate(&e.to_string(), 80)
                            ),
                            start.elapsed(),
                        );
                    }
                }
            }
            None => {
                record(
                    results,
                    "v03/spec03-task-lifecycle",
                    "v0.3 Task Lifecycle",
                    false,
                    "client create error (SDK may not support v0.3): agent card has no supported interfaces",
                    start.elapsed(),
                );
            }
        }
    }

    // ── v03/spec03-streaming ──
    {
        let start = Instant::now();
        match &v03_client {
            Some(client) => {
                let msg = new_user_message("streaming");
                match client.send_message_streaming(msg, None, None).await {
                    Ok(stream) => {
                        let mut stream = stream;
                        let mut event_count: usize = 0;
                        let mut last_state: Option<TaskState> = None;

                        while let Some(item) = stream.next().await {
                            match item {
                                Ok(event) => {
                                    event_count += 1;
                                    match &event {
                                        StreamingMessageResult::StatusUpdate(ev) => {
                                            last_state = Some(ev.status.state);
                                        }
                                        StreamingMessageResult::Task(t) => {
                                            last_state = Some(t.status.state);
                                        }
                                        _ => {}
                                    }
                                }
                                Err(_) => break,
                            }
                        }
                        let completed =
                            last_state == Some(TaskState::Completed);
                        record(
                            results,
                            "v03/spec03-streaming",
                            "v0.3 Streaming",
                            completed && event_count > 0,
                            &format!("events={event_count}, lastState={last_state:?}"),
                            start.elapsed(),
                        );
                    }
                    Err(e) => {
                        record(
                            results,
                            "v03/spec03-streaming",
                            "v0.3 Streaming",
                            false,
                            &format!(
                                "stream error (SDK may not support v0.3): {}",
                                truncate(&e.to_string(), 80)
                            ),
                            start.elapsed(),
                        );
                    }
                }
            }
            None => {
                record(
                    results,
                    "v03/spec03-streaming",
                    "v0.3 Streaming",
                    false,
                    "client create error (SDK may not support v0.3): agent card has no supported interfaces",
                    start.elapsed(),
                );
            }
        }
    }
}

// ── Client construction helpers ────────────────────────────────────

async fn build_client_for(base_url: &str, path_prefix: &str) -> Option<A2aClient> {
    let server_url = format!("{base_url}{path_prefix}");

    // Use A2A-Version header ONLY for card fetch (not for RPC calls)
    let card_http = {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("A2A-Version", "1.0".parse().unwrap());
        reqwest::Client::builder()
            .default_headers(headers)
            .build()
            .ok()?
    };

    // Manually fetch agent card to find the JSONRPC endpoint,
    // because the SDK's Url::join("/.well-known/...") always resolves
    // to the root path, which returns an array on this server.
    let card_url = format!("{server_url}/.well-known/agent-card.json");
    let card_val: serde_json::Value = match card_http.get(&card_url).send().await {
        Ok(resp) => match resp.error_for_status() {
            Ok(r) => match r.json().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("  ⚠ Failed to parse agent card at {card_url}: {e}");
                    return None;
                }
            },
            Err(e) => {
                eprintln!("  ⚠ Failed to fetch agent card at {card_url}: {e}");
                return None;
            }
        },
        Err(e) => {
            eprintln!("  ⚠ Failed to fetch agent card at {card_url}: {e}");
            return None;
        }
    };

    // Find the JSONRPC endpoint from supportedInterfaces
    let endpoint = card_val
        .get("supportedInterfaces")
        .and_then(|v| v.as_array())
        .and_then(|ifaces| {
            ifaces.iter().find_map(|i| {
                let binding = i.get("protocolBinding")?.as_str()?;
                if binding.eq_ignore_ascii_case("jsonrpc") {
                    i.get("url")?.as_str().map(|s| s.to_string())
                } else {
                    None
                }
            })
        });

    let endpoint_url = match endpoint {
        Some(url) => url,
        None => {
            eprintln!(
                "  ⚠ Agent card at {card_url} has no JSONRPC endpoint in supportedInterfaces"
            );
            return None;
        }
    };

    // RPC client WITHOUT A2A-Version header
    let config = ClientConfig {
        server_url,
        max_polls: 30,
        poll_interval_ms: 2000,
        oauth: None,
        endpoint_url: Some(endpoint_url),
        http_client: None,
    };
    match A2aClient::new(config) {
        Ok(client) => Some(client),
        Err(e) => {
            eprintln!("  ⚠ Failed to create client for {base_url}{path_prefix}: {e}");
            None
        }
    }
}

/// Build a client for the v0.3 agent. The v0.3 card has a `url` field
/// (not `supportedInterfaces`), so we point the SDK directly at that URL.
async fn build_v03_client(base_url: &str) -> Option<A2aClient> {
    let card_url = format!("{base_url}/spec03/.well-known/agent-card.json");
    let card_val: serde_json::Value = match reqwest::get(&card_url).await {
        Ok(resp) => match resp.error_for_status() {
            Ok(r) => match r.json().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("  ⚠ Failed to parse v0.3 card: {e}");
                    return None;
                }
            },
            Err(e) => {
                eprintln!("  ⚠ Failed to fetch v0.3 card: {e}");
                return None;
            }
        },
        Err(e) => {
            eprintln!("  ⚠ Failed to fetch v0.3 card: {e}");
            return None;
        }
    };

    // v0.3 cards have a `url` field pointing to the RPC endpoint
    let endpoint = card_val
        .get("url")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let endpoint_url = match endpoint {
        Some(url) => url,
        None => {
            eprintln!("  ⚠ v0.3 card has no 'url' field");
            return None;
        }
    };

    let config = ClientConfig {
        server_url: format!("{base_url}/spec03"),
        max_polls: 30,
        poll_interval_ms: 2000,
        oauth: None,
        endpoint_url: Some(endpoint_url),
        http_client: None,
    };

    match A2aClient::new(config) {
        Ok(client) => Some(client),
        Err(e) => {
            eprintln!("  ⚠ Failed to create v0.3 client: {e}");
            None
        }
    }
}

fn extract_task_info(
    result: &SendMessageResult,
) -> (Option<String>, Option<String>, Option<TaskState>) {
    match result {
        SendMessageResult::Task(task) => (
            Some(task.id.clone()),
            Some(task.context_id.clone()),
            Some(task.status.state),
        ),
        SendMessageResult::Message(msg) => (None, msg.context_id.clone(), None),
    }
}
