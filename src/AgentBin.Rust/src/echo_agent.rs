use a2a_rs_core::{
    AgentCard, AgentCapabilities, AgentInterface, AgentSkill,
    Message, Part, Role, SendMessageResponse, Task, TaskState, TaskStatus,
    now_iso8601, PROTOCOL_VERSION,
};
use a2a_rs_server::{AuthContext, HandlerResult, MessageHandler};
use async_trait::async_trait;
use uuid::Uuid;

pub struct EchoAgent {
    prefix: String,
}

impl EchoAgent {
    pub fn new(prefix: &str) -> Self {
        Self { prefix: prefix.to_string() }
    }
}

#[async_trait]
impl MessageHandler for EchoAgent {
    async fn handle_message(
        &self,
        message: Message,
        _auth: Option<AuthContext>,
    ) -> HandlerResult<SendMessageResponse> {
        let text = extract_text(&message);
        let context_id = message.context_id.clone().unwrap_or_else(|| Uuid::new_v4().to_string());
        let task_id = Uuid::new_v4().to_string();

        let agent_message = Message {
            kind: "message".to_string(),
            message_id: Uuid::new_v4().to_string(),
            context_id: Some(context_id.clone()),
            task_id: Some(task_id.clone()),
            role: Role::Agent,
            parts: vec![Part::text(format!("Echo: {}", text))],
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
                message: Some(agent_message.clone()),
                timestamp: Some(now_iso8601()),
            },
            history: Some(vec![message, agent_message]),
            artifacts: None,
            metadata: None,
        };

        Ok(SendMessageResponse::Task(task))
    }

    fn agent_card(&self, base_url: &str) -> AgentCard {
        AgentCard {
            name: "AgentBin Echo Agent".to_string(),
            description: "Simple echo agent for basic connectivity testing.".to_string(),
            version: "1.0.0".to_string(),
            supported_interfaces: vec![AgentInterface {
                url: format!("{}{}/v1/rpc", base_url, self.prefix),
                protocol_binding: "JSONRPC".to_string(),
                protocol_version: PROTOCOL_VERSION.to_string(),
                tenant: None,
            }],
            provider: None,
            documentation_url: None,
            capabilities: AgentCapabilities::default(),
            security_schemes: Default::default(),
            security_requirements: vec![],
            default_input_modes: vec!["text".to_string()],
            default_output_modes: vec!["text".to_string()],
            skills: vec![AgentSkill {
                id: "echo".to_string(),
                name: "Echo".to_string(),
                description: "Echoes back the user's message".to_string(),
                tags: vec!["echo".to_string()],
                examples: vec!["hello".to_string()],
                input_modes: vec![],
                output_modes: vec![],
                security_requirements: vec![],
            }],
            signatures: vec![],
            icon_url: None,
        }
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
