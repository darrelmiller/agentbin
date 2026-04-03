package main

import "github.com/a2aproject/a2a-go/v2/a2a"

func buildSpecCard(baseURL string) *a2a.AgentCard {
	return &a2a.AgentCard{
		Name:        "AgentBin Spec Agent",
		Description: "A2A v1.0 spec compliance test agent. Exercises all interaction patterns for client validation.",
		Version:     "1.0.0",
		SupportedInterfaces: []*a2a.AgentInterface{
			a2a.NewAgentInterface(baseURL+"/spec", a2a.TransportProtocolJSONRPC),
			a2a.NewAgentInterface(baseURL+"/spec", a2a.TransportProtocolHTTPJSON),
		},
		DefaultInputModes:  []string{"text"},
		DefaultOutputModes: []string{"text"},
		Capabilities: a2a.AgentCapabilities{
			Streaming:         true,
			ExtendedAgentCard: true,
		},
		Skills: specSkills(),
	}
}

func buildExtendedSpecCard(baseURL string) *a2a.AgentCard {
	skills := append(specSkills(), a2a.AgentSkill{
		ID:          "admin-status",
		Name:        "Admin Status",
		Description: "Returns server admin status (requires auth)",
		Tags:        []string{"admin", "status"},
		Examples:    []string{"admin-status"},
	})
	return &a2a.AgentCard{
		Name:        "AgentBin Spec Agent (Extended)",
		Description: "Extended agent card with additional skills (requires authentication).",
		Version:     "1.0.0",
		SupportedInterfaces: []*a2a.AgentInterface{
			a2a.NewAgentInterface(baseURL+"/spec", a2a.TransportProtocolJSONRPC),
			a2a.NewAgentInterface(baseURL+"/spec", a2a.TransportProtocolHTTPJSON),
		},
		DefaultInputModes:  []string{"text"},
		DefaultOutputModes: []string{"text"},
		Capabilities: a2a.AgentCapabilities{
			Streaming:         true,
			ExtendedAgentCard: true,
		},
		Skills: skills,
	}
}

func specSkills() []a2a.AgentSkill {
	return []a2a.AgentSkill{
		{
			ID:          "message-only",
			Name:        "Message Only",
			Description: "Stateless message response (no task created)",
			Tags:        []string{"message", "stateless"},
			Examples:    []string{"message-only hello world"},
		},
		{
			ID:          "task-lifecycle",
			Name:        "Task Lifecycle",
			Description: "Full task: submitted → working → completed",
			Tags:        []string{"task", "lifecycle"},
			Examples:    []string{"task-lifecycle hello world"},
		},
		{
			ID:          "task-failure",
			Name:        "Task Failure",
			Description: "Task that fails with error message",
			Tags:        []string{"task", "failure"},
			Examples:    []string{"task-failure"},
		},
		{
			ID:          "task-cancel",
			Name:        "Task Cancel",
			Description: "Task that waits to be canceled",
			Tags:        []string{"task", "cancel"},
			Examples:    []string{"task-cancel"},
		},
		{
			ID:          "multi-turn",
			Name:        "Multi-Turn",
			Description: "Multi-turn conversation (input-required)",
			Tags:        []string{"multi-turn", "conversation"},
			Examples:    []string{"multi-turn start a conversation"},
		},
		{
			ID:          "streaming",
			Name:        "Streaming",
			Description: "Streamed response with multiple chunks",
			Tags:        []string{"streaming", "sse"},
			Examples:    []string{"streaming"},
		},
		{
			ID:          "long-running",
			Name:        "Long Running",
			Description: "Long-running task with periodic updates",
			Tags:        []string{"long-running", "polling"},
			Examples:    []string{"long-running"},
		},
		{
			ID:          "data-types",
			Name:        "Data Types",
			Description: "Mixed content: text, JSON, file, multi-part",
			Tags:        []string{"data", "artifacts"},
			Examples:    []string{"data-types"},
		},
	}
}

func buildEchoCard(baseURL string) *a2a.AgentCard {
	return &a2a.AgentCard{
		Name:        "AgentBin Echo Agent",
		Description: "Simple echo agent for basic connectivity testing.",
		Version:     "1.0.0",
		SupportedInterfaces: []*a2a.AgentInterface{
			a2a.NewAgentInterface(baseURL+"/echo", a2a.TransportProtocolJSONRPC),
			a2a.NewAgentInterface(baseURL+"/echo", a2a.TransportProtocolHTTPJSON),
		},
		DefaultInputModes:  []string{"text"},
		DefaultOutputModes: []string{"text"},
		Capabilities:       a2a.AgentCapabilities{},
		Skills: []a2a.AgentSkill{
			{
				ID:          "echo",
				Name:        "Echo",
				Description: "Echoes back the user's message",
				Tags:        []string{"echo"},
				Examples:    []string{"hello"},
			},
		},
	}
}
