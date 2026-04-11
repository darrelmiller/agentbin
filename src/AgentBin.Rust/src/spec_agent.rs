use a2a_rs_core::{
    Artifact, AgentCard, AgentCapabilities, AgentInterface, AgentSkill,
    Message, Part, Role, SendMessageResponse, StreamResponse, Task, TaskState, TaskStatus,
    now_iso8601, PROTOCOL_VERSION,
};
use a2a_rs_server::{AuthContext, HandlerResult, MessageHandler};
use async_trait::async_trait;
use serde_json::json;
use std::sync::{Arc, OnceLock};
use tokio::sync::broadcast;
use uuid::Uuid;

pub struct SpecAgent {
    prefix: String,
    event_tx: Arc<OnceLock<broadcast::Sender<StreamResponse>>>,
}

impl SpecAgent {
    pub fn new(prefix: &str, event_tx: Arc<OnceLock<broadcast::Sender<StreamResponse>>>) -> Self {
        Self {
            prefix: prefix.to_string(),
            event_tx,
        }
    }
}

#[async_trait]
impl MessageHandler for SpecAgent {
    async fn handle_message(
        &self,
        message: Message,
        _auth: Option<AuthContext>,
    ) -> HandlerResult<SendMessageResponse> {
        // TCK routes on messageId prefix (tck-*), not on message text
        if message.message_id.starts_with("tck-") {
            return self.route_tck(&message);
        }

        let text = extract_text(&message);
        let (keyword, _rest) = split_keyword(&text);

        match keyword.as_str() {
            "message-only" => self.handle_message_only(text),
            "task-lifecycle" => self.handle_task_lifecycle(&message, text),
            "task-failure" => self.handle_task_failure(&message),
            "task-cancel" => self.handle_task_cancel_sync(&message),
            "multi-turn" => self.handle_multi_turn(&message, text),
            "streaming" => self.handle_streaming_sync(&message),
            "long-running" => self.handle_long_running_sync(&message),
            "data-types" => self.handle_data_types(&message, text),
            _ => self.handle_help(),
        }
    }

    fn agent_card(&self, base_url: &str) -> AgentCard {
        AgentCard {
            name: "AgentBin Spec Agent".to_string(),
            description: "A2A v1.0 spec compliance test agent. Exercises all interaction patterns for client validation.".to_string(),
            version: "1.0.0".to_string(),
            supported_interfaces: vec![AgentInterface {
                url: format!("{}{}/v1/rpc", base_url, self.prefix),
                protocol_binding: "JSONRPC".to_string(),
                protocol_version: PROTOCOL_VERSION.to_string(),
                tenant: None,
            }],
            provider: None,
            documentation_url: None,
            capabilities: AgentCapabilities {
                streaming: Some(true),
                ..Default::default()
            },
            security_schemes: Default::default(),
            security_requirements: vec![],
            default_input_modes: vec!["text".to_string()],
            default_output_modes: vec!["text".to_string()],
            skills: build_skills(),
            signatures: vec![],
            icon_url: None,
        }
    }

    fn supports_streaming(&self) -> bool {
        true
    }

    async fn cancel_task(&self, _task_id: &str) -> HandlerResult<()> {
        Ok(())
    }
}

impl SpecAgent {
    /// Spawn a delayed completion event through the broadcast channel.
    /// This works around an SDK race condition where the stream subscribes to
    /// events AFTER the initial task broadcast, so a terminal task returned
    /// directly from handle_message() would cause the stream to hang forever.
    fn send_delayed_completion(
        &self,
        task_id: String,
        context_id: String,
        status_text: &str,
        artifacts: Option<Vec<Artifact>>,
    ) {
        if let Some(tx) = self.event_tx.get() {
            let tx = tx.clone();
            let status_message = Message {
                kind: "message".to_string(),
                message_id: Uuid::new_v4().to_string(),
                context_id: Some(context_id.clone()),
                task_id: Some(task_id.clone()),
                role: Role::Agent,
                parts: vec![Part::text(status_text)],
                metadata: None,
                extensions: vec![],
                reference_task_ids: None,
            };
            let completed_task = Task {
                kind: "task".to_string(),
                id: task_id,
                context_id,
                status: TaskStatus {
                    state: TaskState::Completed,
                    message: Some(status_message),
                    timestamp: Some(now_iso8601()),
                },
                history: None,
                artifacts,
                metadata: None,
            };
            tokio::spawn(async move {
                // Small delay ensures the SDK has subscribed to the event channel
                tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                let _ = tx.send(StreamResponse::Task(completed_task));
            });
        }
    }

    /// Return a Working task and schedule a delayed Completed event via broadcast.
    /// Used by all TCK streaming handlers to avoid the SDK subscribe race condition.
    fn tck_streaming_task(
        &self,
        message: &Message,
        status_text: &str,
        artifacts: Option<Vec<Artifact>>,
    ) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let working_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(status_text)],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        // Schedule delayed completion via broadcast channel
        self.send_delayed_completion(
            task_id.clone(),
            context_id.clone(),
            status_text,
            artifacts,
        );

        // Return Working task — the stream will see this first, then pick up
        // the Completed task from the broadcast channel
        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Working,
                message: Some(working_message),
                timestamp: Some(now_iso8601()),
            },
            history: None,
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_message_only(&self, text: String) -> HandlerResult<SendMessageResponse> {
        let reply = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: None,
            task_id: None,
            role: Role::Agent,
            parts: vec![Part::text(format!("[message-only] You said: {}", text))],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        Ok(SendMessageResponse::Message(reply))
    }

    fn handle_task_lifecycle(&self, message: &Message, text: String) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let artifact = Artifact {
            artifact_id: "result".to_string(),
            name: Some("The processed result".to_string()),
            description: None,
            parts: vec![Part::text(format!("[task-lifecycle] Processed: {}", text))],
            metadata: None,
            extensions: vec![],
        };

        let agent_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Completed,
                message: None,
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), agent_message]),
            artifacts: Some(vec![artifact]),
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_task_failure(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let fail_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(
                "[task-failure] Simulated failure: this task was designed to fail for testing purposes."
            )],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Failed,
                message: Some(fail_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), fail_message]),
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_task_cancel_sync(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let work_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(
                "[task-cancel] Working... send a cancel request to this task. (Note: Rust implementation returns completed immediately as async cancellation is not supported)"
            )],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Completed,
                message: Some(work_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), work_message]),
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_multi_turn(&self, message: &Message, text: String) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = message.task_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());

        let is_done = text.to_lowercase().contains("done");

        if is_done {
            let artifact = Artifact {
                artifact_id: "final".to_string(),
                name: Some("final".to_string()),
                description: None,
                parts: vec![Part::text(format!("[multi-turn] Final message received: {}", text))],
                metadata: None,
                extensions: vec![],
            };

            let done_message = Message {
                kind: "message".to_string(),
                message_id: Uuid::new_v4().to_string(),
                context_id: Some(context_id.clone()),
                task_id: Some(task_id.clone()),
                role: Role::Agent,
                parts: vec![Part::text(
                    "[multi-turn] Conversation complete. All turns processed successfully."
                )],
                metadata: None,
                extensions: vec![],
                reference_task_ids: None,
            };

            let task = Task {
                kind: "task".to_string(),
                id: task_id,
                context_id,
                status: TaskStatus {
                    state: TaskState::Completed,
                    message: Some(done_message.clone()),
                    timestamp: Some(now_iso8601()),
                },
                history: Some(vec![message.clone(), done_message]),
                artifacts: Some(vec![artifact]),
                metadata: None,
            };

            Ok(SendMessageResponse::Task(task))
        } else {
            let artifact = Artifact {
                artifact_id: "turn-1".to_string(),
                name: Some("turn-1".to_string()),
                description: None,
                parts: vec![Part::text(format!("[multi-turn] Received initial message: {}", text))],
                metadata: None,
                extensions: vec![],
            };

            let prompt_message = Message {
                kind: "message".to_string(),
                message_id: Uuid::new_v4().to_string(),
                context_id: Some(context_id.clone()),
                task_id: Some(task_id.clone()),
                role: Role::Agent,
                parts: vec![Part::text(
                    "[multi-turn] Please send a follow-up message to continue. Say 'done' to complete."
                )],
                metadata: None,
                extensions: vec![],
                reference_task_ids: None,
            };

            let task = Task {
                kind: "task".to_string(),
                id: task_id,
                context_id,
                status: TaskStatus {
                    state: TaskState::InputRequired,
                    message: Some(prompt_message.clone()),
                    timestamp: Some(now_iso8601()),
                },
                history: Some(vec![message.clone(), prompt_message]),
                artifacts: Some(vec![artifact]),
                metadata: None,
            };

            Ok(SendMessageResponse::Task(task))
        }
    }

    fn handle_streaming_sync(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let artifact = Artifact {
            artifact_id: "stream-result".to_string(),
            name: Some("Streamed Result".to_string()),
            description: None,
            parts: vec![
                Part::text("[streaming] Chunk 1: Processing your request..."),
                Part::text("[streaming] Chunk 2: Analyzing input data..."),
                Part::text("[streaming] Chunk 3: Generating results..."),
                Part::text("[streaming] Chunk 4: Finalizing output..."),
            ],
            metadata: None,
            extensions: vec![],
        };

        let working_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(
                "[streaming] Stream complete. 4 chunks delivered."
            )],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        // Schedule delayed completion with artifact via broadcast channel
        self.send_delayed_completion(
            task_id.clone(),
            context_id.clone(),
            "[streaming] Stream complete. 4 chunks delivered.",
            Some(vec![artifact]),
        );

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Working,
                message: Some(working_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), working_message]),
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_long_running_sync(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let mut artifacts = Vec::new();
        for i in 1..=5 {
            artifacts.push(Artifact {
                artifact_id: format!("step-{}", i),
                name: Some(format!("step-{}", i)),
                description: None,
                parts: vec![Part::text(format!(
                    "[long-running] Step {} result: completed at {}",
                    i,
                    chrono::Utc::now().to_rfc3339()
                ))],
                metadata: None,
                extensions: vec![],
            });
        }

        let done_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(
                "[long-running] All 5 steps complete. (Note: Rust implementation returns all steps at once as async processing is not supported)"
            )],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Completed,
                message: Some(done_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), done_message]),
            artifacts: Some(artifacts),
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_data_types(&self, message: &Message, text: String) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let mut artifacts = Vec::new();

        artifacts.push(Artifact {
            artifact_id: "text-artifact".to_string(),
            name: Some("Text Artifact".to_string()),
            description: Some("A simple text artifact".to_string()),
            parts: vec![Part::text("[data-types] This is a plain text artifact.")],
            metadata: None,
            extensions: vec![],
        });

        artifacts.push(Artifact {
            artifact_id: "data-artifact".to_string(),
            name: Some("Structured Data Artifact".to_string()),
            description: Some("A structured JSON data artifact".to_string()),
            parts: vec![Part::data(json!({
                "type": "test-result",
                "timestamp": chrono::Utc::now().to_rfc3339(),
                "input": text,
                "metrics": {
                    "latencyMs": 42,
                    "tokensProcessed": 7
                }
            }))],
            metadata: None,
            extensions: vec![],
        });

        let svg_content = format!(
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="{}"/><text x="50" y="55" text-anchor="middle" fill="white" font-size="14">A2A</text></svg>"#,
            "#4CAF50"
        );
        let svg_base64 = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, svg_content.as_bytes());
        artifacts.push(Artifact {
            artifact_id: "file-artifact".to_string(),
            name: Some("File Artifact".to_string()),
            description: Some("A binary file artifact (SVG image)".to_string()),
            parts: vec![Part::file_bytes(svg_base64, "image/svg+xml")],
            metadata: None,
            extensions: vec![],
        });

        artifacts.push(Artifact {
            artifact_id: "multi-part-artifact".to_string(),
            name: Some("Multi-Part Artifact".to_string()),
            description: Some("An artifact containing both text and structured data parts".to_string()),
            parts: vec![
                Part::text("[data-types] This artifact has multiple parts."),
                Part::data(json!({"multiPart": true, "partCount": 2})),
            ],
            metadata: None,
            extensions: vec![],
        });

        let done_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(
                "[data-types] Generated 4 artifacts with different content types: text, JSON data, file (SVG), and multi-part."
            )],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Completed,
                message: Some(done_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message.clone(), done_message]),
            artifacts: Some(artifacts),
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn handle_help(&self) -> HandlerResult<SendMessageResponse> {
        let help_text = r#"AgentBin Spec Agent — A2A v1.0 Test Bed

Send a message starting with one of these skill keywords:

  message-only    → Stateless message response (no task)
  task-lifecycle  → Full task: submitted → working → completed
  task-failure    → Task that fails with error message
  task-cancel     → Task that waits to be canceled (simplified in Rust)
  multi-turn      → Multi-turn conversation (input-required)
  streaming       → Streamed response with multiple chunks (simplified in Rust)
  long-running    → Long-running task with periodic updates (simplified in Rust)
  data-types      → Mixed content: text, JSON, file, multi-part

Example: "task-lifecycle hello world"

Note: The Rust implementation uses synchronous handlers, so streaming/long-running/cancel
behaviors return completed tasks immediately rather than streaming events over time."#;

        let reply = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: None,
            task_id: None,
            role: Role::Agent,
            parts: vec![Part::text(help_text)],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        Ok(SendMessageResponse::Message(reply))
    }

    // --- TCK (Technology Compatibility Kit) handlers ---

    fn route_tck(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let prefix = extract_tck_prefix(&message.message_id);
        match prefix {
            "complete-task" => self.tck_complete_task(message),
            "artifact-text" => self.tck_artifact_text(message),
            "artifact-file" => self.tck_artifact_file(message),
            "artifact-file-url" => self.tck_artifact_file_url(message),
            "artifact-data" => self.tck_artifact_data(message),
            "message-response" => self.tck_message_response(message),
            "input-required" => self.tck_input_required(message),
            "reject-task" => self.tck_reject_task(message),
            "stream-001" => self.tck_stream_001(message),
            "stream-002" => self.tck_stream_002(message),
            "stream-003" => self.tck_stream_003(message),
            "stream-ordering-001" => self.tck_stream_ordering_001(message),
            "stream-artifact-text" => self.tck_stream_artifact_text(message),
            "stream-artifact-file" => self.tck_stream_artifact_file(message),
            "stream-artifact-chunked" => self.tck_stream_artifact_chunked(message),
            _ => self.handle_help(),
        }
    }

    fn tck_completed_task(
        &self,
        message: &Message,
        status_text: &str,
        artifacts: Option<Vec<Artifact>>,
    ) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let status_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(status_text)],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Completed,
                message: Some(status_message),
                timestamp: Some(now_iso8601()),
            },
            history: None,
            artifacts,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn tck_complete_task(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        self.tck_completed_task(message, "Hello from TCK", None)
    }

    fn tck_artifact_text(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("text-artifact".to_string()),
            description: None,
            parts: vec![Part::text("Generated text content")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_completed_task(message, "Generated text content", Some(vec![artifact]))
    }

    fn tck_artifact_file(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let encoded = base64::Engine::encode(
            &base64::engine::general_purpose::STANDARD,
            b"file content",
        );
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("file-artifact".to_string()),
            description: None,
            parts: vec![Part::file_bytes(encoded, "text/plain")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_completed_task(message, "file content", Some(vec![artifact]))
    }

    fn tck_artifact_file_url(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("file-url-artifact".to_string()),
            description: None,
            parts: vec![Part::file_uri("https://example.com/output.txt", "text/plain")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_completed_task(message, "https://example.com/output.txt", Some(vec![artifact]))
    }

    fn tck_artifact_data(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("data-artifact".to_string()),
            description: None,
            parts: vec![Part::data(json!({"key": "value", "count": 42}))],
            metadata: None,
            extensions: vec![],
        };
        self.tck_completed_task(message, "data artifact", Some(vec![artifact]))
    }

    fn tck_message_response(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let reply = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: message.context_id.clone(),
            task_id: None,
            role: Role::Agent,
            parts: vec![Part::text("Direct message response")],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };
        Ok(SendMessageResponse::Message(reply))
    }

    fn tck_input_required(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let status_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text("Input required — send a follow-up message.")],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::InputRequired,
                message: Some(status_message),
                timestamp: Some(now_iso8601()),
            },
            history: None,
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn tck_reject_task(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let status_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text("rejected")],
            metadata: None,
            extensions: vec![],
            reference_task_ids: None,
        };

        let task = Task {
            kind: "task".to_string(),
            id: task_id,
            context_id,
            status: TaskStatus {
                state: TaskState::Failed,
                message: Some(status_message),
                timestamp: Some(now_iso8601()),
            },
            history: None,
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn tck_stream_001(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("stream-artifact".to_string()),
            description: None,
            parts: vec![Part::text("Stream hello from TCK")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "Stream hello from TCK", Some(vec![artifact]))
    }

    fn tck_stream_002(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        self.tck_streaming_task(message, "Completed", None)
    }

    fn tck_stream_003(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("stream-artifact".to_string()),
            description: None,
            parts: vec![Part::text("Stream task lifecycle")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "Stream task lifecycle", Some(vec![artifact]))
    }

    fn tck_stream_ordering_001(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("stream-artifact".to_string()),
            description: None,
            parts: vec![Part::text("Ordered output")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "Ordered output", Some(vec![artifact]))
    }

    fn tck_stream_artifact_text(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("stream-text-artifact".to_string()),
            description: None,
            parts: vec![Part::text("Streamed text content")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "Streamed text content", Some(vec![artifact]))
    }

    fn tck_stream_artifact_file(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let encoded = base64::Engine::encode(
            &base64::engine::general_purpose::STANDARD,
            b"file content",
        );
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("stream-file-artifact".to_string()),
            description: None,
            parts: vec![Part::file_bytes(encoded, "text/plain")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "file content", Some(vec![artifact]))
    }

    fn tck_stream_artifact_chunked(&self, message: &Message) -> HandlerResult<SendMessageResponse> {
        let artifact = Artifact {
            artifact_id: Uuid::new_v4().to_string(),
            name: Some("chunked-artifact".to_string()),
            description: None,
            parts: vec![Part::text("chunk-1 chunk-2")],
            metadata: None,
            extensions: vec![],
        };
        self.tck_streaming_task(message, "chunk-1 chunk-2", Some(vec![artifact]))
    }
}

fn extract_tck_prefix(message_id: &str) -> &str {
    let without_prefix = &message_id[4..]; // strip "tck-"
    match without_prefix.rfind('-') {
        Some(pos) if pos > 0 => &without_prefix[..pos],
        _ => without_prefix,
    }
}

fn extract_text(message: &Message) -> String {
    message
        .parts
        .iter()
        .filter_map(|p| p.as_text())
        .collect::<Vec<_>>()
        .join("\n")
}

fn split_keyword(text: &str) -> (String, String) {
    let lower = text.trim().to_lowercase();
    let parts: Vec<&str> = lower.splitn(2, ' ').collect();
    let keyword = parts[0].to_string();
    let rest = if parts.len() > 1 {
        parts[1].to_string()
    } else {
        String::new()
    };
    (keyword, rest)
}

fn build_skills() -> Vec<AgentSkill> {
    vec![
        AgentSkill {
            id: "message-only".to_string(),
            name: "Message Only".to_string(),
            description: "Stateless message response (no task created)".to_string(),
            tags: vec!["message".to_string(), "stateless".to_string()],
            examples: vec!["message-only hello world".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "task-lifecycle".to_string(),
            name: "Task Lifecycle".to_string(),
            description: "Full task: submitted → working → completed".to_string(),
            tags: vec!["task".to_string(), "lifecycle".to_string()],
            examples: vec!["task-lifecycle hello world".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "task-failure".to_string(),
            name: "Task Failure".to_string(),
            description: "Task that fails with error message".to_string(),
            tags: vec!["task".to_string(), "failure".to_string()],
            examples: vec!["task-failure".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "task-cancel".to_string(),
            name: "Task Cancel".to_string(),
            description: "Task that waits to be canceled".to_string(),
            tags: vec!["task".to_string(), "cancel".to_string()],
            examples: vec!["task-cancel".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "multi-turn".to_string(),
            name: "Multi-Turn".to_string(),
            description: "Multi-turn conversation (input-required)".to_string(),
            tags: vec!["multi-turn".to_string(), "conversation".to_string()],
            examples: vec!["multi-turn start a conversation".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "streaming".to_string(),
            name: "Streaming".to_string(),
            description: "Streamed response with multiple chunks".to_string(),
            tags: vec!["streaming".to_string(), "sse".to_string()],
            examples: vec!["streaming".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "long-running".to_string(),
            name: "Long Running".to_string(),
            description: "Long-running task with periodic updates".to_string(),
            tags: vec!["long-running".to_string(), "polling".to_string()],
            examples: vec!["long-running".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
        AgentSkill {
            id: "data-types".to_string(),
            name: "Data Types".to_string(),
            description: "Mixed content: text, JSON, file, multi-part".to_string(),
            tags: vec!["data".to_string(), "artifacts".to_string()],
            examples: vec!["data-types".to_string()],
            input_modes: vec![],
            output_modes: vec![],
            security_requirements: vec![],
        },
    ]
}
