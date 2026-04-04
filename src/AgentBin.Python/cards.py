"""Agent card builders for AgentBin Python server."""

from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentInterface
from google.protobuf.json_format import MessageToDict


def card_to_wire_dict(card: AgentCard, base_url: str, path: str) -> dict:
    """Convert an AgentCard protobuf to a wire-format dict compatible with all SDKs."""
    return MessageToDict(card, preserving_proto_field_name=False)


def build_spec_card(base_url: str) -> AgentCard:
    """Build the SpecAgent card."""
    return AgentCard(
        name="AgentBin Spec Agent",
        description="A2A v1.0 spec compliance test agent. Exercises all interaction patterns for client validation.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=f"{base_url}/spec", protocol_binding="JSONRPC", protocol_version="1.0"),
            AgentInterface(url=f"{base_url}/spec", protocol_binding="HTTP+JSON", protocol_version="1.0"),
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=True,
            extended_agent_card=True,
        ),
        skills=spec_skills(),
    )


def build_extended_spec_card(base_url: str) -> AgentCard:
    """Build the extended SpecAgent card (with admin skill)."""
    skills = list(spec_skills())
    skills.append(
        AgentSkill(
            id="admin-status",
            name="Admin Status",
            description="Returns server admin status (requires auth)",
            tags=["admin", "status"],
            examples=["admin-status"],
        )
    )
    return AgentCard(
        name="AgentBin Spec Agent (Extended)",
        description="Extended agent card with additional skills (requires authentication).",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=f"{base_url}/spec", protocol_binding="JSONRPC", protocol_version="1.0"),
            AgentInterface(url=f"{base_url}/spec", protocol_binding="HTTP+JSON", protocol_version="1.0"),
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=True,
            extended_agent_card=True,
        ),
        skills=skills,
    )


def spec_skills() -> list[AgentSkill]:
    """Build the list of spec agent skills."""
    return [
        AgentSkill(
            id="message-only",
            name="Message Only",
            description="Stateless message response (no task created)",
            tags=["message", "stateless"],
            examples=["message-only hello world"],
        ),
        AgentSkill(
            id="task-lifecycle",
            name="Task Lifecycle",
            description="Full task: submitted → working → completed",
            tags=["task", "lifecycle"],
            examples=["task-lifecycle hello world"],
        ),
        AgentSkill(
            id="task-failure",
            name="Task Failure",
            description="Task that fails with error message",
            tags=["task", "failure"],
            examples=["task-failure"],
        ),
        AgentSkill(
            id="task-cancel",
            name="Task Cancel",
            description="Task that waits to be canceled",
            tags=["task", "cancel"],
            examples=["task-cancel"],
        ),
        AgentSkill(
            id="multi-turn",
            name="Multi-Turn",
            description="Multi-turn conversation (input-required)",
            tags=["multi-turn", "conversation"],
            examples=["multi-turn start a conversation"],
        ),
        AgentSkill(
            id="streaming",
            name="Streaming",
            description="Streamed response with multiple chunks",
            tags=["streaming", "sse"],
            examples=["streaming"],
        ),
        AgentSkill(
            id="long-running",
            name="Long Running",
            description="Long-running task with periodic updates",
            tags=["long-running", "polling"],
            examples=["long-running"],
        ),
        AgentSkill(
            id="data-types",
            name="Data Types",
            description="Mixed content: text, JSON, file, multi-part",
            tags=["data", "artifacts"],
            examples=["data-types"],
        ),
    ]


def build_echo_card(base_url: str) -> AgentCard:
    """Build the EchoAgent card."""
    return AgentCard(
        name="AgentBin Echo Agent",
        description="Simple echo agent for basic connectivity testing.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=f"{base_url}/echo", protocol_binding="JSONRPC", protocol_version="1.0"),
            AgentInterface(url=f"{base_url}/echo", protocol_binding="HTTP+JSON", protocol_version="1.0"),
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="echo",
                name="Echo",
                description="Echoes back the user's message",
                tags=["echo"],
                examples=["hello"],
            ),
        ],
    )
