package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2aclient"
	"github.com/a2aproject/a2a-go/a2aclient/agentcard"
	"github.com/google/uuid"
)

const defaultBaseURL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"

// TestResult represents a single test outcome.
type TestResult struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Passed     bool   `json:"passed"`
	Detail     string `json:"detail"`
	DurationMs int64  `json:"durationMs"`
}

// TestReport is the top-level JSON output.
type TestReport struct {
	Client          string       `json:"client"`
	SDK             string       `json:"sdk"`
	ProtocolVersion string       `json:"protocolVersion"`
	Timestamp       string       `json:"timestamp"`
	BaseURL         string       `json:"baseUrl"`
	Results         []TestResult `json:"results"`
}

var results []TestResult

func record(id, name string, passed bool, detail string, dur time.Duration) {
	results = append(results, TestResult{
		ID:         id,
		Name:       name,
		Passed:     passed,
		Detail:     detail,
		DurationMs: dur.Milliseconds(),
	})
	status := "PASS"
	if !passed {
		status = "FAIL"
	}
	fmt.Printf("  [%s] %s — %s\n", status, id, detail)
}

func main() {
	baseURL := defaultBaseURL
	if len(os.Args) > 1 {
		baseURL = os.Args[1]
	}

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	fmt.Println("=== Go A2A Client Tests ===")
	fmt.Printf("Base URL: %s\n\n", baseURL)

	var echoCard, specCard *a2a.AgentCard
	var savedTaskID a2a.TaskID

	versionHeader := agentcard.WithRequestHeader("A2A-Version", "1.0")

	// 1. agent-card-echo
	{
		start := time.Now()
		card, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/echo", versionHeader)
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/agent-card-echo", "Echo Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			echoCard = card
			record("jsonrpc/agent-card-echo", "Echo Agent Card", true,
				fmt.Sprintf("name=%s, skills=%d", card.Name, len(card.Skills)), dur)
		}
	}

	// 2. agent-card-spec
	{
		start := time.Now()
		card, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/spec", versionHeader)
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/agent-card-spec", "Spec Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			specCard = card
			record("jsonrpc/agent-card-spec", "Spec Agent Card", true,
				fmt.Sprintf("name=%s, skills=%d", card.Name, len(card.Skills)), dur)
		}
	}

	// 3. echo-send-message
	if echoCard != nil {
		start := time.Now()
		client, err := a2aclient.NewFromCard(ctx, echoCard)
		if err != nil {
			record("jsonrpc/echo-send-message", "Echo Send Message", false, fmt.Sprintf("client error: %v", err), time.Since(start))
		} else {
			defer client.Destroy()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hello from Go"))
			resp, err := client.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			dur := time.Since(start)
			if err != nil {
				record("jsonrpc/echo-send-message", "Echo Send Message", false, fmt.Sprintf("error: %v", err), dur)
			} else {
				text := extractResultText(resp)
				hasEcho := strings.Contains(strings.ToLower(text), "hello")
				record("jsonrpc/echo-send-message", "Echo Send Message", hasEcho,
					fmt.Sprintf("response=%s", truncate(text, 120)), dur)
			}
		}
	} else {
		record("jsonrpc/echo-send-message", "Echo Send Message", false, "skipped — no echo card", 0)
	}

	// Create a shared spec client for tests 4-10
	var specClient *a2aclient.Client
	if specCard != nil {
		c, err := a2aclient.NewFromCard(ctx, specCard)
		if err != nil {
			fmt.Printf("  [FAIL] spec client creation: %v\n", err)
		} else {
			specClient = c
			defer specClient.Destroy()
		}
	}

	// 4. spec-message-only
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only"))
		resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-message-only", "Message Only", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Message:
				text := extractText(v.Parts)
				record("jsonrpc/spec-message-only", "Message Only", true,
					fmt.Sprintf("got Message, text=%s", truncate(text, 100)), dur)
			case *a2a.Task:
				record("jsonrpc/spec-message-only", "Message Only", false,
					fmt.Sprintf("expected Message, got Task(state=%s)", v.Status.State), dur)
			default:
				record("jsonrpc/spec-message-only", "Message Only", false,
					fmt.Sprintf("unexpected type %T", resp), dur)
			}
		}
	} else {
		record("jsonrpc/spec-message-only", "Message Only", false, "skipped — no spec client", 0)
	}

	// 5. spec-task-lifecycle
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
		resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Task:
				savedTaskID = v.ID
				passed := v.Status.State == a2a.TaskStateCompleted
				record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", passed,
					fmt.Sprintf("state=%s, artifacts=%d, id=%s", v.Status.State, len(v.Artifacts), v.ID), dur)
			case *a2a.Message:
				record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false, "expected Task, got Message", dur)
			default:
				record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false,
					fmt.Sprintf("unexpected type %T", resp), dur)
			}
		}
	} else {
		record("jsonrpc/spec-task-lifecycle", "Task Lifecycle", false, "skipped — no spec client", 0)
	}

	// 6. spec-get-task
	if specClient != nil && savedTaskID != "" {
		start := time.Now()
		task, err := specClient.GetTask(ctx, &a2a.GetTaskRequest{ID: savedTaskID})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-get-task", "Get Task", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := task.ID == savedTaskID
			record("jsonrpc/spec-get-task", "Get Task", passed,
				fmt.Sprintf("id=%s, state=%s", task.ID, task.Status.State), dur)
		}
	} else {
		detail := "skipped — no spec client"
		if specClient != nil {
			detail = "skipped — no task ID from lifecycle test"
		}
		record("jsonrpc/spec-get-task", "Get Task", false, detail, 0)
	}

	// 7. spec-task-failure
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-failure"))
		resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-task-failure", "Task Failure", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Task:
				passed := v.Status.State == a2a.TaskStateFailed
				record("jsonrpc/spec-task-failure", "Task Failure", passed,
					fmt.Sprintf("state=%s", v.Status.State), dur)
			default:
				record("jsonrpc/spec-task-failure", "Task Failure", false,
					fmt.Sprintf("expected failed Task, got %T", resp), dur)
			}
		}
	} else {
		record("jsonrpc/spec-task-failure", "Task Failure", false, "skipped — no spec client", 0)
	}

	// 8. spec-data-types
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("data-types"))
		resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-data-types", "Data Types", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			hasText, hasData, hasFile := false, false, false
			for _, p := range collectAllParts(resp) {
				if p == nil || p.Content == nil {
					continue
				}
				switch p.Content.(type) {
				case a2a.Text:
					hasText = true
				case a2a.Data:
					hasData = true
				case a2a.Raw, a2a.URL:
					hasFile = true
				}
			}
			passed := hasText && hasData && hasFile
			record("jsonrpc/spec-data-types", "Data Types", passed,
				fmt.Sprintf("text=%v, data=%v, file=%v", hasText, hasData, hasFile), dur)
		}
	} else {
		record("jsonrpc/spec-data-types", "Data Types", false, "skipped — no spec client", 0)
	}

	// 9. spec-streaming
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("streaming"))
		eventCount := 0
		var lastState a2a.TaskState
		var lastHasArtifact bool
		var streamErr error
		for event, err := range specClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
			if err != nil {
				streamErr = err
				break
			}
			eventCount++
			switch v := event.(type) {
			case *a2a.TaskStatusUpdateEvent:
				lastState = v.Status.State
			case *a2a.TaskArtifactUpdateEvent:
				lastHasArtifact = true
			case *a2a.Task:
				lastState = v.Status.State
				if len(v.Artifacts) > 0 {
					lastHasArtifact = true
				}
			}
		}
		dur := time.Since(start)
		if streamErr != nil {
			record("jsonrpc/spec-streaming", "Streaming", false, fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := eventCount > 1 && (lastState == a2a.TaskStateCompleted || lastHasArtifact)
			record("jsonrpc/spec-streaming", "Streaming", passed,
				fmt.Sprintf("events=%d, lastState=%s, hasArtifact=%v", eventCount, lastState, lastHasArtifact), dur)
		}
	} else {
		record("jsonrpc/spec-streaming", "Streaming", false, "skipped — no spec client", 0)
	}

	// 10. error-task-not-found
	if specClient != nil {
		start := time.Now()
		_, err := specClient.GetTask(ctx, &a2a.GetTaskRequest{ID: "00000000-0000-0000-0000-000000000000"})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/error-task-not-found", "Task Not Found Error", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("jsonrpc/error-task-not-found", "Task Not Found Error", false, "expected error, got nil", dur)
		}
	} else {
		record("jsonrpc/error-task-not-found", "Task Not Found Error", false, "skipped — no spec client", 0)
	}

	// ── HTTP+JSON REST Binding ──
	fmt.Println("\n── HTTP+JSON REST Binding ──")

	var restTaskID string

	// 1. rest/agent-card-echo
	{
		start := time.Now()
		status, body, err := restGet(baseURL + "/echo/v1/card")
		dur := time.Since(start)
		if err != nil {
			record("rest/agent-card-echo", "REST Echo Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/agent-card-echo", "REST Echo Agent Card", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			hasName := strings.Contains(body, `"name"`)
			record("rest/agent-card-echo", "REST Echo Agent Card", hasName,
				fmt.Sprintf("status=%d, hasName=%v", status, hasName), dur)
		}
	}

	// 2. rest/agent-card-spec
	{
		start := time.Now()
		status, body, err := restGet(baseURL + "/spec/v1/card")
		dur := time.Since(start)
		if err != nil {
			record("rest/agent-card-spec", "REST Spec Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/agent-card-spec", "REST Spec Agent Card", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			hasSkills := strings.Contains(body, `"skills"`)
			record("rest/agent-card-spec", "REST Spec Agent Card", hasSkills,
				fmt.Sprintf("status=%d, hasSkills=%v", status, hasSkills), dur)
		}
	}

	// 3. rest/echo-send-message
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"hello from Go REST"}]}}`, msgID)
		status, body, err := restPost(baseURL+"/echo/v1/message:send", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/echo-send-message", "REST Echo Send Message", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/echo-send-message", "REST Echo Send Message", false, fmt.Sprintf("status=%d body=%s", status, truncate(body, 100)), dur)
		} else {
			hasHello := strings.Contains(strings.ToLower(body), "hello")
			record("rest/echo-send-message", "REST Echo Send Message", hasHello,
				fmt.Sprintf("status=%d, hasHello=%v, body=%s", status, hasHello, truncate(body, 120)), dur)
		}
	}

	// 4. rest/spec-message-only
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"message-only"}]}}`, msgID)
		status, body, err := restPost(baseURL+"/spec/v1/message:send", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-message-only", "REST Message Only", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/spec-message-only", "REST Message Only", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			var parsed map[string]interface{}
			json.Unmarshal([]byte(body), &parsed)
			_, hasMessage := parsed["message"]
			_, hasTask := parsed["task"]
			passed := hasMessage && !hasTask
			record("rest/spec-message-only", "REST Message Only", passed,
				fmt.Sprintf("hasMessage=%v, hasTask=%v", hasMessage, hasTask), dur)
		}
	}

	// 5. rest/spec-task-lifecycle
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"task-lifecycle"}]}}`, msgID)
		status, body, err := restPost(baseURL+"/spec/v1/message:send", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-task-lifecycle", "REST Task Lifecycle", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/spec-task-lifecycle", "REST Task Lifecycle", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			var parsed map[string]interface{}
			json.Unmarshal([]byte(body), &parsed)
			passed := false
			if taskObj, ok := parsed["task"].(map[string]interface{}); ok {
				if id, ok := taskObj["id"].(string); ok {
					restTaskID = id
				}
				if statusObj, ok := taskObj["status"].(map[string]interface{}); ok {
					state, _ := statusObj["state"].(string)
					passed = state == "TASK_STATE_COMPLETED"
				}
				artifacts, hasArtifacts := taskObj["artifacts"].([]interface{})
				record("rest/spec-task-lifecycle", "REST Task Lifecycle", passed,
					fmt.Sprintf("taskId=%s, hasArtifacts=%v(%d)", restTaskID, hasArtifacts, len(artifacts)), dur)
			} else {
				record("rest/spec-task-lifecycle", "REST Task Lifecycle", false,
					fmt.Sprintf("no task in response: %s", truncate(body, 100)), dur)
			}
		}
	}

	// 6. rest/spec-get-task
	if restTaskID != "" {
		start := time.Now()
		status, body, err := restGet(baseURL + "/spec/v1/tasks/" + restTaskID)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-get-task", "REST Get Task", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/spec-get-task", "REST Get Task", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			var parsed map[string]interface{}
			json.Unmarshal([]byte(body), &parsed)
			id, _ := parsed["id"].(string)
			passed := id == restTaskID
			record("rest/spec-get-task", "REST Get Task", passed,
				fmt.Sprintf("id=%s, expected=%s", id, restTaskID), dur)
		}
	} else {
		record("rest/spec-get-task", "REST Get Task", false, "skipped — no task ID from lifecycle test", 0)
	}

	// 7. rest/spec-task-failure
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"task-failure"}]}}`, msgID)
		status, body, err := restPost(baseURL+"/spec/v1/message:send", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-task-failure", "REST Task Failure", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/spec-task-failure", "REST Task Failure", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			var parsed map[string]interface{}
			json.Unmarshal([]byte(body), &parsed)
			passed := false
			if taskObj, ok := parsed["task"].(map[string]interface{}); ok {
				if statusObj, ok := taskObj["status"].(map[string]interface{}); ok {
					state, _ := statusObj["state"].(string)
					passed = state == "TASK_STATE_FAILED"
					record("rest/spec-task-failure", "REST Task Failure", passed,
						fmt.Sprintf("state=%s", state), dur)
				} else {
					record("rest/spec-task-failure", "REST Task Failure", false, "no status in task", dur)
				}
			} else {
				record("rest/spec-task-failure", "REST Task Failure", false,
					fmt.Sprintf("no task in response: %s", truncate(body, 100)), dur)
			}
		}
	}

	// 8. rest/spec-data-types
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"data-types"}]}}`, msgID)
		status, body, err := restPost(baseURL+"/spec/v1/message:send", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-data-types", "REST Data Types", false, fmt.Sprintf("error: %v", err), dur)
		} else if status != 200 {
			record("rest/spec-data-types", "REST Data Types", false, fmt.Sprintf("status=%d", status), dur)
		} else {
			hasText := strings.Contains(body, `"text"`)
			hasData := strings.Contains(body, `"data"`)
			hasMediaType := strings.Contains(body, `"mediaType"`)
			passed := hasText && hasData && hasMediaType
			record("rest/spec-data-types", "REST Data Types", passed,
				fmt.Sprintf("hasText=%v, hasData=%v, hasMediaType=%v", hasText, hasData, hasMediaType), dur)
		}
	}

	// 9. rest/spec-streaming
	{
		start := time.Now()
		msgID := uuid.New().String()
		reqBody := fmt.Sprintf(`{"message":{"messageId":"%s","role":"ROLE_USER","parts":[{"text":"streaming"}]}}`, msgID)
		dataLines, err := restStream(baseURL+"/spec/v1/message:stream", reqBody)
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-streaming", "REST Streaming", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := dataLines >= 3
			record("rest/spec-streaming", "REST Streaming", passed,
				fmt.Sprintf("dataLines=%d (need>=3)", dataLines), dur)
		}
	}

	// 10. rest/error-task-not-found
	{
		start := time.Now()
		status, _, err := restGet(baseURL + "/spec/v1/tasks/00000000-0000-0000-0000-000000000000")
		dur := time.Since(start)
		if err != nil {
			record("rest/error-task-not-found", "REST Task Not Found", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := status == 404
			record("rest/error-task-not-found", "REST Task Not Found", passed,
				fmt.Sprintf("status=%d (expected 404)", status), dur)
		}
	}

	// Summary
	fmt.Println("\n========================================")
	passed, failed := 0, 0
	for _, r := range results {
		if r.Passed {
			passed++
		} else {
			failed++
		}
	}
	fmt.Printf("Total: %d passed, %d failed out of %d\n", passed, failed, len(results))

	// Write results.json next to the binary or working directory
	report := TestReport{
		Client:          "go",
		SDK:             "a2a-go",
		ProtocolVersion: "1.0",
		Timestamp:       time.Now().UTC().Format(time.RFC3339),
		BaseURL:         baseURL,
		Results:         results,
	}
	writeJSON(report)

	if failed > 0 {
		os.Exit(1)
	}
}

func writeJSON(report TestReport) {
	dir, _ := os.Getwd()
	path := filepath.Join(dir, "results.json")
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to marshal results: %v\n", err)
		return
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to write %s: %v\n", path, err)
		return
	}
	fmt.Printf("Results written to %s\n", path)
}

func extractResultText(resp a2a.SendMessageResult) string {
	switch v := resp.(type) {
	case *a2a.Message:
		return extractText(v.Parts)
	case *a2a.Task:
		if v.Status.Message != nil {
			if t := extractText(v.Status.Message.Parts); t != "" {
				return t
			}
		}
		for _, art := range v.Artifacts {
			if t := extractText(art.Parts); t != "" {
				return t
			}
		}
	}
	return ""
}

func extractText(parts a2a.ContentParts) string {
	var texts []string
	for _, p := range parts {
		if p != nil && p.Content != nil {
			if t, ok := p.Content.(a2a.Text); ok {
				texts = append(texts, string(t))
			}
		}
	}
	return strings.Join(texts, " ")
}

func collectAllParts(resp a2a.SendMessageResult) []*a2a.Part {
	var all []*a2a.Part
	switch v := resp.(type) {
	case *a2a.Message:
		all = append(all, v.Parts...)
	case *a2a.Task:
		if v.Status.Message != nil {
			all = append(all, v.Status.Message.Parts...)
		}
		for _, art := range v.Artifacts {
			all = append(all, art.Parts...)
		}
	}
	return all
}

func truncate(s string, max int) string {
	if len(s) > max {
		return s[:max] + "..."
	}
	return s
}

// REST binding helpers

func restGet(url string) (int, string, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("A2A-Version", "1.0")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, "", err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, "", err
	}
	return resp.StatusCode, string(b), nil
}

func restPost(url, jsonBody string) (int, string, error) {
	req, err := http.NewRequest("POST", url, bytes.NewBufferString(jsonBody))
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("A2A-Version", "1.0")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, "", err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, "", err
	}
	return resp.StatusCode, string(b), nil
}

func restStream(url, jsonBody string) (int, error) {
	req, err := http.NewRequest("POST", url, bytes.NewBufferString(jsonBody))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("A2A-Version", "1.0")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return 0, fmt.Errorf("stream status %d", resp.StatusCode)
	}
	dataLines := 0
	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data:") {
			dataLines++
		}
	}
	if err := scanner.Err(); err != nil {
		return dataLines, err
	}
	return dataLines, nil
}
