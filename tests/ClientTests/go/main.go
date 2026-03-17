package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2aclient"
	"github.com/a2aproject/a2a-go/v2/a2aclient/agentcard"
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

func detectSDKSource() string {
	// Check if go.mod has a replace directive for a2a-go (local build)
	goMod, err := os.ReadFile("go.mod")
	if err != nil {
		return "a2a-go"
	}
	for _, line := range strings.Split(string(goMod), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "replace") && strings.Contains(line, "a2a-go") {
			parts := strings.Split(line, "=>")
			if len(parts) == 2 {
				localPath := strings.TrimSpace(parts[1])
				// Try to get git branch from the local path
				gitDir := filepath.Join(localPath, ".git")
				if head, err := os.ReadFile(filepath.Join(gitDir, "HEAD")); err == nil {
					ref := strings.TrimSpace(string(head))
					if strings.HasPrefix(ref, "ref: refs/heads/") {
						branch := strings.TrimPrefix(ref, "ref: refs/heads/")
						return fmt.Sprintf("a2a-go@%s (local)", branch)
					}
				}
				return fmt.Sprintf("a2a-go (local: %s)", localPath)
			}
		}
	}
	// Check go.sum for the version
	goSum, err := os.ReadFile("go.sum")
	if err != nil {
		return "a2a-go"
	}
	for _, line := range strings.Split(string(goSum), "\n") {
		if strings.Contains(line, "a2a-go") && !strings.Contains(line, "/go.mod") {
			parts := strings.Fields(line)
			if len(parts) >= 2 {
				return "a2a-go " + parts[1]
			}
		}
	}
	return "a2a-go"
}

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

	// 11. spec-multi-turn (3-step multi-turn conversation)
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			// Step 1: Start conversation
			msg1 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("multi-turn start conversation"))
			resp1, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg1})
			if err != nil {
				return false, fmt.Sprintf("step1 error: %v", err)
			}
			task1, ok := resp1.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step1: expected Task, got %T", resp1)
			}
			if task1.Status.State != a2a.TaskStateInputRequired {
				return false, fmt.Sprintf("step1: expected INPUT_REQUIRED, got %s", task1.Status.State)
			}
			taskID := task1.ID

			// Step 2: Follow-up with taskId
			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up message"))
			msg2.TaskID = taskID
			resp2, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return false, fmt.Sprintf("step2 error: %v", err)
			}
			task2, ok := resp2.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step2: expected Task, got %T", resp2)
			}
			if task2.Status.State != a2a.TaskStateInputRequired {
				return false, fmt.Sprintf("step2: expected INPUT_REQUIRED, got %s", task2.Status.State)
			}

			// Step 3: Send "done" to complete
			msg3 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("done"))
			msg3.TaskID = taskID
			resp3, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg3})
			if err != nil {
				return false, fmt.Sprintf("step3 error: %v", err)
			}
			task3, ok := resp3.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step3: expected Task, got %T", resp3)
			}
			if task3.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("step3: expected COMPLETED, got %s", task3.Status.State)
			}
			return true, fmt.Sprintf("taskId=%s, 3 steps completed", taskID)
		}()
		record("jsonrpc/spec-multi-turn", "Multi-Turn Conversation", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/spec-multi-turn", "Multi-Turn Conversation", false, "skipped — no spec client", 0)
	}

	// 12. spec-task-cancel (cancel a task via streaming)
	if specClient != nil {
		cancelCtx, cancelTimeout := context.WithTimeout(ctx, 10*time.Second)
		start := time.Now()
		passed, detail := func() (bool, string) {
			defer cancelTimeout()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-cancel"))
			var streamTaskID a2a.TaskID
			var lastState a2a.TaskState
			cancelSent := false

			for event, err := range specClient.SendStreamingMessage(cancelCtx, &a2a.SendMessageRequest{Message: msg}) {
				if err != nil {
					if cancelSent {
						break
					}
					return false, fmt.Sprintf("stream error: %v", err)
				}
				switch v := event.(type) {
				case *a2a.TaskStatusUpdateEvent:
					if streamTaskID == "" {
						streamTaskID = v.TaskID
					}
					lastState = v.Status.State
				case *a2a.TaskArtifactUpdateEvent:
					if streamTaskID == "" {
						streamTaskID = v.TaskID
					}
				case *a2a.Task:
					if streamTaskID == "" {
						streamTaskID = a2a.TaskID(v.ID)
					}
					lastState = v.Status.State
				}
				if streamTaskID != "" && !cancelSent {
					cancelSent = true
					specClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: streamTaskID})
				}
			}

			if streamTaskID == "" {
				return false, "no task ID from stream"
			}
			if lastState == a2a.TaskStateCanceled {
				return true, fmt.Sprintf("taskId=%s, state=CANCELED", streamTaskID)
			}
			// Fallback: check via GetTask
			task, err := specClient.GetTask(ctx, &a2a.GetTaskRequest{ID: streamTaskID})
			if err != nil {
				return false, fmt.Sprintf("taskId=%s, lastStreamState=%s, getTask error: %v", streamTaskID, lastState, err)
			}
			p := task.Status.State == a2a.TaskStateCanceled
			return p, fmt.Sprintf("taskId=%s, state=%s (via GetTask)", streamTaskID, task.Status.State)
		}()
		record("jsonrpc/spec-task-cancel", "Task Cancel", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/spec-task-cancel", "Task Cancel", false, "skipped — no spec client", 0)
	}

	// 13. spec-list-tasks
	if specClient != nil {
		start := time.Now()
		resp, err := specClient.ListTasks(ctx, &a2a.ListTasksRequest{})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/spec-list-tasks", "List Tasks", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := len(resp.Tasks) >= 1
			record("jsonrpc/spec-list-tasks", "List Tasks", passed,
				fmt.Sprintf("tasks=%d (need>=1)", len(resp.Tasks)), dur)
		}
	} else {
		record("jsonrpc/spec-list-tasks", "List Tasks", false, "skipped — no spec client", 0)
	}

	// 14. spec-return-immediately (EXPECTED TO FAIL)
	if specClient != nil {
		riCtx, riCancel := context.WithTimeout(ctx, 15*time.Second)
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("long-running test"))
		resp, err := specClient.SendMessage(riCtx, &a2a.SendMessageRequest{
			Message: msg,
			Config:  &a2a.SendMessageConfig{ReturnImmediately: true},
		})
		dur := time.Since(start)
		riCancel()
		if err != nil {
			record("jsonrpc/spec-return-immediately", "Return Immediately", false,
				fmt.Sprintf("error: %v (returnImmediately ignored by SDK)", err), dur)
		} else {
			elapsed := dur.Seconds()
			var state a2a.TaskState
			if v, ok := resp.(*a2a.Task); ok {
				state = v.Status.State
			}
			if elapsed > 3 || state == a2a.TaskStateCompleted {
				record("jsonrpc/spec-return-immediately", "Return Immediately", false,
					fmt.Sprintf("took %.1fs, state=%s — returnImmediately ignored by SDK", elapsed, state), dur)
			} else if elapsed < 2 && state != a2a.TaskStateCompleted {
				record("jsonrpc/spec-return-immediately", "Return Immediately", true,
					fmt.Sprintf("took %.1fs, state=%s — returned promptly", elapsed, state), dur)
			} else {
				record("jsonrpc/spec-return-immediately", "Return Immediately", false,
					fmt.Sprintf("took %.1fs, state=%s — inconclusive", elapsed, state), dur)
			}
		}
	} else {
		record("jsonrpc/spec-return-immediately", "Return Immediately", false, "skipped — no spec client", 0)
	}

	// 15. error-cancel-not-found
	if specClient != nil {
		start := time.Now()
		_, err := specClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: "00000000-0000-0000-0000-000000000000"})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/error-cancel-not-found", "Cancel Not Found Error", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("jsonrpc/error-cancel-not-found", "Cancel Not Found Error", false, "expected error, got nil", dur)
		}
	} else {
		record("jsonrpc/error-cancel-not-found", "Cancel Not Found Error", false, "skipped — no spec client", 0)
	}

	// 16. error-cancel-terminal
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			if task.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("expected COMPLETED, got %s", task.Status.State)
			}
			_, err = specClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: task.ID})
			if err != nil {
				isExpected := errors.Is(err, a2a.ErrTaskNotCancelable)
				return true, fmt.Sprintf("got error (isTaskNotCancelable=%v): %s", isExpected, truncate(err.Error(), 80))
			}
			return false, "expected error canceling completed task, got nil"
		}()
		record("jsonrpc/error-cancel-terminal", "Cancel Terminal Error", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/error-cancel-terminal", "Cancel Terminal Error", false, "skipped — no spec client", 0)
	}

	// 17. error-send-terminal
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			if task.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("expected COMPLETED, got %s", task.Status.State)
			}
			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up after done"))
			msg2.TaskID = task.ID
			_, err = specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return true, fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100))
			}
			return false, "expected error sending to completed task, got nil"
		}()
		record("jsonrpc/error-send-terminal", "Send Terminal Error", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/error-send-terminal", "Send Terminal Error", false, "skipped — no spec client", 0)
	}

	// 18. error-send-invalid-task
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hello"))
		msg.TaskID = "00000000-0000-0000-0000-000000000000"
		_, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("jsonrpc/error-send-invalid-task", "Send Invalid Task Error", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("jsonrpc/error-send-invalid-task", "Send Invalid Task Error", false, "expected error, got nil", dur)
		}
	} else {
		record("jsonrpc/error-send-invalid-task", "Send Invalid Task Error", false, "skipped — no spec client", 0)
	}

	// 19. error-push-not-supported
	if specClient != nil {
		start := time.Now()
		_, err := specClient.CreateTaskPushConfig(ctx, &a2a.CreateTaskPushConfigRequest{
			TaskID: "00000000-0000-0000-0000-000000000000",
			Config: a2a.PushConfig{URL: "https://example.com/webhook"},
		})
		dur := time.Since(start)
		if err != nil {
			isExpected := errors.Is(err, a2a.ErrPushNotificationNotSupported)
			record("jsonrpc/error-push-not-supported", "Push Not Supported Error", true,
				fmt.Sprintf("got error (isPushNotSupported=%v): %s", isExpected, truncate(err.Error(), 80)), dur)
		} else {
			record("jsonrpc/error-push-not-supported", "Push Not Supported Error", false, "expected error, got nil", dur)
		}
	} else {
		record("jsonrpc/error-push-not-supported", "Push Not Supported Error", false, "skipped — no spec client", 0)
	}

	// 20. subscribe-to-task
	if specClient != nil {
		subCtx, subCancel := context.WithTimeout(ctx, 15*time.Second)
		start := time.Now()
		passed, detail := func() (bool, string) {
			defer subCancel()
			// Start a long-running task via streaming to get a WORKING task ID
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-cancel"))
			var taskID a2a.TaskID
			for event, err := range specClient.SendStreamingMessage(subCtx, &a2a.SendMessageRequest{Message: msg}) {
				if err != nil {
					return false, fmt.Sprintf("stream error: %v", err)
				}
				switch v := event.(type) {
				case *a2a.TaskStatusUpdateEvent:
					taskID = v.TaskID
				case *a2a.TaskArtifactUpdateEvent:
					taskID = v.TaskID
				case *a2a.Task:
					taskID = a2a.TaskID(v.ID)
				}
				if taskID != "" {
					break
				}
			}
			if taskID == "" {
				return false, "no task ID from stream"
			}

			subEventCount := 0
			for _, err := range specClient.SubscribeToTask(subCtx, &a2a.SubscribeToTaskRequest{ID: taskID}) {
				if err != nil {
					if subEventCount > 0 {
						break
					}
					return false, fmt.Sprintf("subscribe error: %v", err)
				}
				subEventCount++
				if subEventCount >= 1 {
					// Cancel the task to end the subscription
					specClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: taskID})
					break
				}
			}
			if subEventCount >= 1 {
				return true, fmt.Sprintf("taskId=%s, subscriptionEvents=%d", taskID, subEventCount)
			}
			return false, fmt.Sprintf("taskId=%s, no subscription events received", taskID)
		}()
		record("jsonrpc/subscribe-to-task", "Subscribe To Task", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/subscribe-to-task", "Subscribe To Task", false, "skipped — no spec client", 0)
	}

	// 21. error-subscribe-not-found
	if specClient != nil {
		subCtx, subCancel := context.WithTimeout(ctx, 10*time.Second)
		start := time.Now()
		var gotErr bool
		var errDetail string
		for _, err := range specClient.SubscribeToTask(subCtx, &a2a.SubscribeToTaskRequest{ID: "00000000-0000-0000-0000-000000000000"}) {
			if err != nil {
				gotErr = true
				errDetail = truncate(err.Error(), 100)
				break
			}
			break // If we get an event without error, that's unexpected
		}
		dur := time.Since(start)
		subCancel()
		if gotErr {
			record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found Error", true,
				fmt.Sprintf("got expected error: %s", errDetail), dur)
		} else {
			record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found Error", false, "expected error, got nil or event", dur)
		}
	} else {
		record("jsonrpc/error-subscribe-not-found", "Subscribe Not Found Error", false, "skipped — no spec client", 0)
	}

	// 22. stream-message-only
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only hello"))
		eventCount := 0
		var gotMessage bool
		var streamErr error
		for event, err := range specClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
			if err != nil {
				streamErr = err
				break
			}
			eventCount++
			if _, ok := event.(*a2a.Message); ok {
				gotMessage = true
			}
		}
		dur := time.Since(start)
		if streamErr != nil {
			record("jsonrpc/stream-message-only", "Stream Message Only", false,
				fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := eventCount == 1 && gotMessage
			record("jsonrpc/stream-message-only", "Stream Message Only", passed,
				fmt.Sprintf("events=%d, gotMessage=%v", eventCount, gotMessage), dur)
		}
	} else {
		record("jsonrpc/stream-message-only", "Stream Message Only", false, "skipped — no spec client", 0)
	}

	// 23. stream-task-lifecycle
	if specClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle process"))
		var gotTaskEvent bool
		var lastState a2a.TaskState
		var streamErr error
		for event, err := range specClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
			if err != nil {
				streamErr = err
				break
			}
			switch v := event.(type) {
			case *a2a.TaskStatusUpdateEvent:
				gotTaskEvent = true
				lastState = v.Status.State
			case *a2a.Task:
				gotTaskEvent = true
				lastState = v.Status.State
			}
		}
		dur := time.Since(start)
		if streamErr != nil {
			record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", false,
				fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := gotTaskEvent && lastState == a2a.TaskStateCompleted
			record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", passed,
				fmt.Sprintf("gotTaskEvent=%v, lastState=%s", gotTaskEvent, lastState), dur)
		}
	} else {
		record("jsonrpc/stream-task-lifecycle", "Stream Task Lifecycle", false, "skipped — no spec client", 0)
	}

	// 24. multi-turn-context-preserved
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg1 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("multi-turn start"))
			resp1, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg1})
			if err != nil {
				return false, fmt.Sprintf("step1 error: %v", err)
			}
			task1, ok := resp1.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step1: expected Task, got %T", resp1)
			}
			contextID := task1.ContextID
			if contextID == "" {
				return false, "step1: task has no ContextID"
			}

			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up"))
			msg2.TaskID = task1.ID
			resp2, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return false, fmt.Sprintf("step2 error: %v", err)
			}
			task2, ok := resp2.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step2: expected Task, got %T", resp2)
			}
			if task2.ContextID != contextID {
				return false, fmt.Sprintf("contextID mismatch: %s vs %s", contextID, task2.ContextID)
			}
			return true, fmt.Sprintf("taskId=%s, contextID=%s preserved", task1.ID, contextID)
		}()
		record("jsonrpc/multi-turn-context-preserved", "Multi-Turn Context Preserved", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/multi-turn-context-preserved", "Multi-Turn Context Preserved", false, "skipped — no spec client", 0)
	}

	// 25. get-task-with-history
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			histLen := 10
			got, err := specClient.GetTask(ctx, &a2a.GetTaskRequest{ID: task.ID, HistoryLength: &histLen})
			if err != nil {
				return false, fmt.Sprintf("getTask error: %v", err)
			}
			return true, fmt.Sprintf("taskId=%s, state=%s, historyLen=%d", got.ID, got.Status.State, len(got.History))
		}()
		record("jsonrpc/get-task-with-history", "Get Task With History", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/get-task-with-history", "Get Task With History", false, "skipped — no spec client", 0)
	}

	// 26. get-task-after-failure
	if specClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-failure"))
			resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			got, err := specClient.GetTask(ctx, &a2a.GetTaskRequest{ID: task.ID})
			if err != nil {
				return false, fmt.Sprintf("getTask error: %v", err)
			}
			isFailed := got.Status.State == a2a.TaskStateFailed
			hasMessage := got.Status.Message != nil
			return isFailed && hasMessage, fmt.Sprintf("state=%s, hasMessage=%v", got.Status.State, hasMessage)
		}()
		record("jsonrpc/get-task-after-failure", "Get Task After Failure", passed, detail, time.Since(start))
	} else {
		record("jsonrpc/get-task-after-failure", "Get Task After Failure", false, "skipped — no spec client", 0)
	}

	// ── HTTP+JSON REST Binding ──
	fmt.Println("\n── HTTP+JSON REST Binding ──")

	var restEchoCard, restSpecCard *a2a.AgentCard
	var restTaskID a2a.TaskID

	// 1. rest/agent-card-echo
	{
		start := time.Now()
		card, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/echo", versionHeader)
		dur := time.Since(start)
		if err != nil {
			record("rest/agent-card-echo", "REST Echo Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			hasREST := false
			for _, iface := range card.SupportedInterfaces {
				if iface.ProtocolBinding == a2a.TransportProtocolHTTPJSON {
					hasREST = true
					break
				}
			}
			if hasREST {
				restEchoCard = card
				record("rest/agent-card-echo", "REST Echo Agent Card", true,
					fmt.Sprintf("name=%s, skills=%d, hasHTTPJSON=true", card.Name, len(card.Skills)), dur)
			} else {
				record("rest/agent-card-echo", "REST Echo Agent Card", false, "card has no HTTP+JSON interface", dur)
			}
		}
	}

	// 2. rest/agent-card-spec
	{
		start := time.Now()
		card, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/spec", versionHeader)
		dur := time.Since(start)
		if err != nil {
			record("rest/agent-card-spec", "REST Spec Agent Card", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			hasREST := false
			for _, iface := range card.SupportedInterfaces {
				if iface.ProtocolBinding == a2a.TransportProtocolHTTPJSON {
					hasREST = true
					break
				}
			}
			if hasREST {
				restSpecCard = card
				record("rest/agent-card-spec", "REST Spec Agent Card", true,
					fmt.Sprintf("name=%s, skills=%d, hasHTTPJSON=true", card.Name, len(card.Skills)), dur)
			} else {
				record("rest/agent-card-spec", "REST Spec Agent Card", false, "card has no HTTP+JSON interface", dur)
			}
		}
	}

	// Helper to create a REST-only client from a card's HTTP+JSON interface
	createRESTClient := func(card *a2a.AgentCard) (*a2aclient.Client, error) {
		var restIface *a2a.AgentInterface
		for _, iface := range card.SupportedInterfaces {
			if iface.ProtocolBinding == a2a.TransportProtocolHTTPJSON {
				restIface = iface
				break
			}
		}
		if restIface == nil {
			return nil, fmt.Errorf("card has no HTTP+JSON interface")
		}
		return a2aclient.NewFromEndpoints(ctx, []*a2a.AgentInterface{restIface})
	}

	// 3. rest/echo-send-message
	if restEchoCard != nil {
		start := time.Now()
		echoRESTClient, err := createRESTClient(restEchoCard)
		if err != nil {
			record("rest/echo-send-message", "REST Echo Send Message", false, fmt.Sprintf("client error: %v", err), time.Since(start))
		} else {
			defer echoRESTClient.Destroy()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hello from Go REST"))
			resp, err := echoRESTClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			dur := time.Since(start)
			if err != nil {
				record("rest/echo-send-message", "REST Echo Send Message", false, fmt.Sprintf("error: %v", err), dur)
			} else {
				text := extractResultText(resp)
				hasEcho := strings.Contains(strings.ToLower(text), "hello")
				record("rest/echo-send-message", "REST Echo Send Message", hasEcho,
					fmt.Sprintf("response=%s", truncate(text, 120)), dur)
			}
		}
	} else {
		record("rest/echo-send-message", "REST Echo Send Message", false, "skipped — no REST echo card", 0)
	}

	// Create a shared REST spec client for tests 4-14
	var restSpecClient *a2aclient.Client
	if restSpecCard != nil {
		c, err := createRESTClient(restSpecCard)
		if err != nil {
			fmt.Printf("  [FAIL] REST spec client creation: %v\n", err)
		} else {
			restSpecClient = c
			defer restSpecClient.Destroy()
		}
	}

	// 4. rest/spec-message-only
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only"))
		resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-message-only", "REST Message Only", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Message:
				text := extractText(v.Parts)
				record("rest/spec-message-only", "REST Message Only", true,
					fmt.Sprintf("got Message, text=%s", truncate(text, 100)), dur)
			case *a2a.Task:
				record("rest/spec-message-only", "REST Message Only", false,
					fmt.Sprintf("expected Message, got Task(state=%s)", v.Status.State), dur)
			default:
				record("rest/spec-message-only", "REST Message Only", false,
					fmt.Sprintf("unexpected type %T", resp), dur)
			}
		}
	} else {
		record("rest/spec-message-only", "REST Message Only", false, "skipped — no REST spec client", 0)
	}

	// 5. rest/spec-task-lifecycle
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
		resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-task-lifecycle", "REST Task Lifecycle", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Task:
				restTaskID = v.ID
				passed := v.Status.State == a2a.TaskStateCompleted
				record("rest/spec-task-lifecycle", "REST Task Lifecycle", passed,
					fmt.Sprintf("state=%s, artifacts=%d, id=%s", v.Status.State, len(v.Artifacts), v.ID), dur)
			case *a2a.Message:
				record("rest/spec-task-lifecycle", "REST Task Lifecycle", false, "expected Task, got Message", dur)
			default:
				record("rest/spec-task-lifecycle", "REST Task Lifecycle", false,
					fmt.Sprintf("unexpected type %T", resp), dur)
			}
		}
	} else {
		record("rest/spec-task-lifecycle", "REST Task Lifecycle", false, "skipped — no REST spec client", 0)
	}

	// 6. rest/spec-get-task
	if restSpecClient != nil && restTaskID != "" {
		start := time.Now()
		task, err := restSpecClient.GetTask(ctx, &a2a.GetTaskRequest{ID: restTaskID})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-get-task", "REST Get Task", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := task.ID == restTaskID
			record("rest/spec-get-task", "REST Get Task", passed,
				fmt.Sprintf("id=%s, state=%s", task.ID, task.Status.State), dur)
		}
	} else {
		detail := "skipped — no REST spec client"
		if restSpecClient != nil {
			detail = "skipped — no task ID from lifecycle test"
		}
		record("rest/spec-get-task", "REST Get Task", false, detail, 0)
	}

	// 7. rest/spec-task-failure
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-failure"))
		resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-task-failure", "REST Task Failure", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			switch v := resp.(type) {
			case *a2a.Task:
				passed := v.Status.State == a2a.TaskStateFailed
				record("rest/spec-task-failure", "REST Task Failure", passed,
					fmt.Sprintf("state=%s", v.Status.State), dur)
			default:
				record("rest/spec-task-failure", "REST Task Failure", false,
					fmt.Sprintf("expected failed Task, got %T", resp), dur)
			}
		}
	} else {
		record("rest/spec-task-failure", "REST Task Failure", false, "skipped — no REST spec client", 0)
	}

	// 8. rest/spec-data-types
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("data-types"))
		resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-data-types", "REST Data Types", false, fmt.Sprintf("error: %v", err), dur)
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
			record("rest/spec-data-types", "REST Data Types", passed,
				fmt.Sprintf("text=%v, data=%v, file=%v", hasText, hasData, hasFile), dur)
		}
	} else {
		record("rest/spec-data-types", "REST Data Types", false, "skipped — no REST spec client", 0)
	}

	// 9. rest/spec-streaming
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("streaming"))
		eventCount := 0
		var lastState a2a.TaskState
		var lastHasArtifact bool
		var streamErr error
		for event, err := range restSpecClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
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
			record("rest/spec-streaming", "REST Streaming", false, fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := eventCount > 1 && (lastState == a2a.TaskStateCompleted || lastHasArtifact)
			record("rest/spec-streaming", "REST Streaming", passed,
				fmt.Sprintf("events=%d, lastState=%s, hasArtifact=%v", eventCount, lastState, lastHasArtifact), dur)
		}
	} else {
		record("rest/spec-streaming", "REST Streaming", false, "skipped — no REST spec client", 0)
	}

	// 10. rest/error-task-not-found
	if restSpecClient != nil {
		start := time.Now()
		_, err := restSpecClient.GetTask(ctx, &a2a.GetTaskRequest{ID: "00000000-0000-0000-0000-000000000000"})
		dur := time.Since(start)
		if err != nil {
			record("rest/error-task-not-found", "REST Task Not Found", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("rest/error-task-not-found", "REST Task Not Found", false, "expected error, got nil", dur)
		}
	} else {
		record("rest/error-task-not-found", "REST Task Not Found", false, "skipped — no REST spec client", 0)
	}

	// 11. rest/spec-multi-turn (3-step multi-turn conversation)
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			// Step 1: Start conversation
			msg1 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("multi-turn start conversation"))
			resp1, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg1})
			if err != nil {
				return false, fmt.Sprintf("step1 error: %v", err)
			}
			task1, ok := resp1.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step1: expected Task, got %T", resp1)
			}
			if task1.Status.State != a2a.TaskStateInputRequired {
				return false, fmt.Sprintf("step1: expected INPUT_REQUIRED, got %s", task1.Status.State)
			}
			taskID := task1.ID

			// Step 2: Follow-up with taskId
			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up message"))
			msg2.TaskID = taskID
			resp2, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return false, fmt.Sprintf("step2 error: %v", err)
			}
			task2, ok := resp2.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step2: expected Task, got %T", resp2)
			}
			if task2.Status.State != a2a.TaskStateInputRequired {
				return false, fmt.Sprintf("step2: expected INPUT_REQUIRED, got %s", task2.Status.State)
			}

			// Step 3: Send "done" to complete
			msg3 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("done"))
			msg3.TaskID = taskID
			resp3, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg3})
			if err != nil {
				return false, fmt.Sprintf("step3 error: %v", err)
			}
			task3, ok := resp3.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step3: expected Task, got %T", resp3)
			}
			if task3.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("step3: expected COMPLETED, got %s", task3.Status.State)
			}
			return true, fmt.Sprintf("taskId=%s, 3 steps completed", taskID)
		}()
		record("rest/spec-multi-turn", "REST Multi-Turn Conversation", passed, detail, time.Since(start))
	} else {
		record("rest/spec-multi-turn", "REST Multi-Turn Conversation", false, "skipped — no REST spec client", 0)
	}

	// 12. rest/spec-task-cancel (cancel a task via streaming)
	if restSpecClient != nil {
		cancelCtx, cancelTimeout := context.WithTimeout(ctx, 10*time.Second)
		start := time.Now()
		passed, detail := func() (bool, string) {
			defer cancelTimeout()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-cancel"))
			var streamTaskID a2a.TaskID
			var lastState a2a.TaskState
			cancelSent := false

			for event, err := range restSpecClient.SendStreamingMessage(cancelCtx, &a2a.SendMessageRequest{Message: msg}) {
				if err != nil {
					if cancelSent {
						break
					}
					return false, fmt.Sprintf("stream error: %v", err)
				}
				switch v := event.(type) {
				case *a2a.TaskStatusUpdateEvent:
					if streamTaskID == "" {
						streamTaskID = v.TaskID
					}
					lastState = v.Status.State
				case *a2a.TaskArtifactUpdateEvent:
					if streamTaskID == "" {
						streamTaskID = v.TaskID
					}
				case *a2a.Task:
					if streamTaskID == "" {
						streamTaskID = a2a.TaskID(v.ID)
					}
					lastState = v.Status.State
				}
				if streamTaskID != "" && !cancelSent {
					cancelSent = true
					restSpecClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: streamTaskID})
				}
			}

			if streamTaskID == "" {
				return false, "no task ID from stream"
			}
			if lastState == a2a.TaskStateCanceled {
				return true, fmt.Sprintf("taskId=%s, state=CANCELED", streamTaskID)
			}
			// Fallback: check via GetTask
			task, err := restSpecClient.GetTask(ctx, &a2a.GetTaskRequest{ID: streamTaskID})
			if err != nil {
				return false, fmt.Sprintf("taskId=%s, lastStreamState=%s, getTask error: %v", streamTaskID, lastState, err)
			}
			p := task.Status.State == a2a.TaskStateCanceled
			return p, fmt.Sprintf("taskId=%s, state=%s (via GetTask)", streamTaskID, task.Status.State)
		}()
		record("rest/spec-task-cancel", "REST Task Cancel", passed, detail, time.Since(start))
	} else {
		record("rest/spec-task-cancel", "REST Task Cancel", false, "skipped — no REST spec client", 0)
	}

	// 13. rest/spec-list-tasks
	if restSpecClient != nil {
		start := time.Now()
		resp, err := restSpecClient.ListTasks(ctx, &a2a.ListTasksRequest{})
		dur := time.Since(start)
		if err != nil {
			record("rest/spec-list-tasks", "REST List Tasks", false, fmt.Sprintf("error: %v", err), dur)
		} else {
			passed := len(resp.Tasks) >= 1
			record("rest/spec-list-tasks", "REST List Tasks", passed,
				fmt.Sprintf("tasks=%d (need>=1)", len(resp.Tasks)), dur)
		}
	} else {
		record("rest/spec-list-tasks", "REST List Tasks", false, "skipped — no REST spec client", 0)
	}

	// 14. rest/spec-return-immediately (EXPECTED TO FAIL)
	if restSpecClient != nil {
		riCtx, riCancel := context.WithTimeout(ctx, 15*time.Second)
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("long-running test"))
		resp, err := restSpecClient.SendMessage(riCtx, &a2a.SendMessageRequest{
			Message: msg,
			Config:  &a2a.SendMessageConfig{ReturnImmediately: true},
		})
		dur := time.Since(start)
		riCancel()
		if err != nil {
			record("rest/spec-return-immediately", "REST Return Immediately", false,
				fmt.Sprintf("error: %v", err), dur)
		} else {
			elapsed := dur.Seconds()
			var state a2a.TaskState
			if v, ok := resp.(*a2a.Task); ok {
				state = v.Status.State
			}
			if elapsed > 3 || state == a2a.TaskStateCompleted {
				record("rest/spec-return-immediately", "REST Return Immediately", false,
					fmt.Sprintf("took %.1fs, state=%s — returnImmediately ignored by SDK", elapsed, state), dur)
			} else if elapsed < 2 && state != a2a.TaskStateCompleted {
				record("rest/spec-return-immediately", "REST Return Immediately", true,
					fmt.Sprintf("took %.1fs, state=%s — returned promptly", elapsed, state), dur)
			} else {
				record("rest/spec-return-immediately", "REST Return Immediately", false,
					fmt.Sprintf("took %.1fs, state=%s — inconclusive", elapsed, state), dur)
			}
		}
	} else {
		record("rest/spec-return-immediately", "REST Return Immediately", false, "skipped — no REST spec client", 0)
	}

	// 15. rest/error-cancel-not-found
	if restSpecClient != nil {
		start := time.Now()
		_, err := restSpecClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: "00000000-0000-0000-0000-000000000000"})
		dur := time.Since(start)
		if err != nil {
			record("rest/error-cancel-not-found", "REST Cancel Not Found Error", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("rest/error-cancel-not-found", "REST Cancel Not Found Error", false, "expected error, got nil", dur)
		}
	} else {
		record("rest/error-cancel-not-found", "REST Cancel Not Found Error", false, "skipped — no REST spec client", 0)
	}

	// 16. rest/error-cancel-terminal
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			if task.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("expected COMPLETED, got %s", task.Status.State)
			}
			_, err = restSpecClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: task.ID})
			if err != nil {
				isExpected := errors.Is(err, a2a.ErrTaskNotCancelable)
				return true, fmt.Sprintf("got error (isTaskNotCancelable=%v): %s", isExpected, truncate(err.Error(), 80))
			}
			return false, "expected error canceling completed task, got nil"
		}()
		record("rest/error-cancel-terminal", "REST Cancel Terminal Error", passed, detail, time.Since(start))
	} else {
		record("rest/error-cancel-terminal", "REST Cancel Terminal Error", false, "skipped — no REST spec client", 0)
	}

	// 17. rest/error-send-terminal
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			if task.Status.State != a2a.TaskStateCompleted {
				return false, fmt.Sprintf("expected COMPLETED, got %s", task.Status.State)
			}
			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up after done"))
			msg2.TaskID = task.ID
			_, err = restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return true, fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100))
			}
			return false, "expected error sending to completed task, got nil"
		}()
		record("rest/error-send-terminal", "REST Send Terminal Error", passed, detail, time.Since(start))
	} else {
		record("rest/error-send-terminal", "REST Send Terminal Error", false, "skipped — no REST spec client", 0)
	}

	// 18. rest/error-send-invalid-task
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hello"))
		msg.TaskID = "00000000-0000-0000-0000-000000000000"
		_, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
		dur := time.Since(start)
		if err != nil {
			record("rest/error-send-invalid-task", "REST Send Invalid Task Error", true,
				fmt.Sprintf("got expected error: %s", truncate(err.Error(), 100)), dur)
		} else {
			record("rest/error-send-invalid-task", "REST Send Invalid Task Error", false, "expected error, got nil", dur)
		}
	} else {
		record("rest/error-send-invalid-task", "REST Send Invalid Task Error", false, "skipped — no REST spec client", 0)
	}

	// 19. rest/error-push-not-supported
	if restSpecClient != nil {
		start := time.Now()
		_, err := restSpecClient.CreateTaskPushConfig(ctx, &a2a.CreateTaskPushConfigRequest{
			TaskID: "00000000-0000-0000-0000-000000000000",
			Config: a2a.PushConfig{URL: "https://example.com/webhook"},
		})
		dur := time.Since(start)
		if err != nil {
			isExpected := errors.Is(err, a2a.ErrPushNotificationNotSupported)
			record("rest/error-push-not-supported", "REST Push Not Supported Error", true,
				fmt.Sprintf("got error (isPushNotSupported=%v): %s", isExpected, truncate(err.Error(), 80)), dur)
		} else {
			record("rest/error-push-not-supported", "REST Push Not Supported Error", false, "expected error, got nil", dur)
		}
	} else {
		record("rest/error-push-not-supported", "REST Push Not Supported Error", false, "skipped — no REST spec client", 0)
	}

	// 20. rest/subscribe-to-task
	if restSpecClient != nil {
		subCtx, subCancel := context.WithTimeout(ctx, 15*time.Second)
		start := time.Now()
		passed, detail := func() (bool, string) {
			defer subCancel()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-cancel"))
			var taskID a2a.TaskID
			for event, err := range restSpecClient.SendStreamingMessage(subCtx, &a2a.SendMessageRequest{Message: msg}) {
				if err != nil {
					return false, fmt.Sprintf("stream error: %v", err)
				}
				switch v := event.(type) {
				case *a2a.TaskStatusUpdateEvent:
					taskID = v.TaskID
				case *a2a.TaskArtifactUpdateEvent:
					taskID = v.TaskID
				case *a2a.Task:
					taskID = a2a.TaskID(v.ID)
				}
				if taskID != "" {
					break
				}
			}
			if taskID == "" {
				return false, "no task ID from stream"
			}

			subEventCount := 0
			for _, err := range restSpecClient.SubscribeToTask(subCtx, &a2a.SubscribeToTaskRequest{ID: taskID}) {
				if err != nil {
					if subEventCount > 0 {
						break
					}
					return false, fmt.Sprintf("subscribe error: %v", err)
				}
				subEventCount++
				if subEventCount >= 1 {
					restSpecClient.CancelTask(ctx, &a2a.CancelTaskRequest{ID: taskID})
					break
				}
			}
			if subEventCount >= 1 {
				return true, fmt.Sprintf("taskId=%s, subscriptionEvents=%d", taskID, subEventCount)
			}
			return false, fmt.Sprintf("taskId=%s, no subscription events received", taskID)
		}()
		record("rest/subscribe-to-task", "REST Subscribe To Task", passed, detail, time.Since(start))
	} else {
		record("rest/subscribe-to-task", "REST Subscribe To Task", false, "skipped — no REST spec client", 0)
	}

	// 21. rest/error-subscribe-not-found
	if restSpecClient != nil {
		subCtx, subCancel := context.WithTimeout(ctx, 10*time.Second)
		start := time.Now()
		var gotErr bool
		var errDetail string
		for _, err := range restSpecClient.SubscribeToTask(subCtx, &a2a.SubscribeToTaskRequest{ID: "00000000-0000-0000-0000-000000000000"}) {
			if err != nil {
				gotErr = true
				errDetail = truncate(err.Error(), 100)
				break
			}
			break
		}
		dur := time.Since(start)
		subCancel()
		if gotErr {
			record("rest/error-subscribe-not-found", "REST Subscribe Not Found Error", true,
				fmt.Sprintf("got expected error: %s", errDetail), dur)
		} else {
			record("rest/error-subscribe-not-found", "REST Subscribe Not Found Error", false, "expected error, got nil or event", dur)
		}
	} else {
		record("rest/error-subscribe-not-found", "REST Subscribe Not Found Error", false, "skipped — no REST spec client", 0)
	}

	// 22. rest/stream-message-only
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only hello"))
		eventCount := 0
		var gotMessage bool
		var streamErr error
		for event, err := range restSpecClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
			if err != nil {
				streamErr = err
				break
			}
			eventCount++
			if _, ok := event.(*a2a.Message); ok {
				gotMessage = true
			}
		}
		dur := time.Since(start)
		if streamErr != nil {
			record("rest/stream-message-only", "REST Stream Message Only", false,
				fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := eventCount == 1 && gotMessage
			record("rest/stream-message-only", "REST Stream Message Only", passed,
				fmt.Sprintf("events=%d, gotMessage=%v", eventCount, gotMessage), dur)
		}
	} else {
		record("rest/stream-message-only", "REST Stream Message Only", false, "skipped — no REST spec client", 0)
	}

	// 23. rest/stream-task-lifecycle
	if restSpecClient != nil {
		start := time.Now()
		msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle process"))
		var gotTaskEvent bool
		var lastState a2a.TaskState
		var streamErr error
		for event, err := range restSpecClient.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
			if err != nil {
				streamErr = err
				break
			}
			switch v := event.(type) {
			case *a2a.TaskStatusUpdateEvent:
				gotTaskEvent = true
				lastState = v.Status.State
			case *a2a.Task:
				gotTaskEvent = true
				lastState = v.Status.State
			}
		}
		dur := time.Since(start)
		if streamErr != nil {
			record("rest/stream-task-lifecycle", "REST Stream Task Lifecycle", false,
				fmt.Sprintf("error: %v", streamErr), dur)
		} else {
			passed := gotTaskEvent && lastState == a2a.TaskStateCompleted
			record("rest/stream-task-lifecycle", "REST Stream Task Lifecycle", passed,
				fmt.Sprintf("gotTaskEvent=%v, lastState=%s", gotTaskEvent, lastState), dur)
		}
	} else {
		record("rest/stream-task-lifecycle", "REST Stream Task Lifecycle", false, "skipped — no REST spec client", 0)
	}

	// 24. rest/multi-turn-context-preserved
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg1 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("multi-turn start"))
			resp1, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg1})
			if err != nil {
				return false, fmt.Sprintf("step1 error: %v", err)
			}
			task1, ok := resp1.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step1: expected Task, got %T", resp1)
			}
			contextID := task1.ContextID
			if contextID == "" {
				return false, "step1: task has no ContextID"
			}

			msg2 := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("follow-up"))
			msg2.TaskID = task1.ID
			resp2, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg2})
			if err != nil {
				return false, fmt.Sprintf("step2 error: %v", err)
			}
			task2, ok := resp2.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("step2: expected Task, got %T", resp2)
			}
			if task2.ContextID != contextID {
				return false, fmt.Sprintf("contextID mismatch: %s vs %s", contextID, task2.ContextID)
			}
			return true, fmt.Sprintf("taskId=%s, contextID=%s preserved", task1.ID, contextID)
		}()
		record("rest/multi-turn-context-preserved", "REST Multi-Turn Context Preserved", passed, detail, time.Since(start))
	} else {
		record("rest/multi-turn-context-preserved", "REST Multi-Turn Context Preserved", false, "skipped — no REST spec client", 0)
	}

	// 25. rest/get-task-with-history
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle"))
			resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			histLen := 10
			got, err := restSpecClient.GetTask(ctx, &a2a.GetTaskRequest{ID: task.ID, HistoryLength: &histLen})
			if err != nil {
				return false, fmt.Sprintf("getTask error: %v", err)
			}
			return true, fmt.Sprintf("taskId=%s, state=%s, historyLen=%d", got.ID, got.Status.State, len(got.History))
		}()
		record("rest/get-task-with-history", "REST Get Task With History", passed, detail, time.Since(start))
	} else {
		record("rest/get-task-with-history", "REST Get Task With History", false, "skipped — no REST spec client", 0)
	}

	// 26. rest/get-task-after-failure
	if restSpecClient != nil {
		start := time.Now()
		passed, detail := func() (bool, string) {
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-failure"))
			resp, err := restSpecClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				return false, fmt.Sprintf("send error: %v", err)
			}
			task, ok := resp.(*a2a.Task)
			if !ok {
				return false, fmt.Sprintf("expected Task, got %T", resp)
			}
			got, err := restSpecClient.GetTask(ctx, &a2a.GetTaskRequest{ID: task.ID})
			if err != nil {
				return false, fmt.Sprintf("getTask error: %v", err)
			}
			isFailed := got.Status.State == a2a.TaskStateFailed
			hasMessage := got.Status.Message != nil
			return isFailed && hasMessage, fmt.Sprintf("state=%s, hasMessage=%v", got.Status.State, hasMessage)
		}()
		record("rest/get-task-after-failure", "REST Get Task After Failure", passed, detail, time.Since(start))
	} else {
		record("rest/get-task-after-failure", "REST Get Task After Failure", false, "skipped — no REST spec client", 0)
	}

	// ── v0.3 Backward Compatibility Tests ──
	fmt.Println("\n── v0.3 Backward Compatibility ──")

	// v03/spec03-agent-card — Raw HTTP GET to verify v0.3 card format
	{
		start := time.Now()
		cardURL := baseURL + "/spec03/.well-known/agent-card.json"
		httpResp, err := http.Get(cardURL)
		dur := time.Since(start)
		if err != nil {
			record("v03/spec03-agent-card", "v0.3 Agent Card", false, fmt.Sprintf("HTTP error: %v", err), dur)
		} else {
			body, readErr := io.ReadAll(httpResp.Body)
			httpResp.Body.Close()
			if readErr != nil {
				record("v03/spec03-agent-card", "v0.3 Agent Card", false, fmt.Sprintf("read error: %v", readErr), dur)
			} else if httpResp.StatusCode != 200 {
				record("v03/spec03-agent-card", "v0.3 Agent Card", false,
					fmt.Sprintf("status=%d, body=%s", httpResp.StatusCode, truncate(string(body), 100)), dur)
			} else {
				var cardData map[string]interface{}
				if jsonErr := json.Unmarshal(body, &cardData); jsonErr != nil {
					record("v03/spec03-agent-card", "v0.3 Agent Card", false, fmt.Sprintf("JSON parse error: %v", jsonErr), dur)
				} else {
					pv, _ := cardData["protocolVersion"].(string)
					_, hasURL := cardData["url"]
					passed := pv == "0.3.0" && hasURL
					record("v03/spec03-agent-card", "v0.3 Agent Card", passed,
						fmt.Sprintf("protocolVersion=%s, hasUrl=%v", pv, hasURL), dur)
				}
			}
		}
	}

	// v03/spec03-send-message — SDK send message to v0.3 agent
	{
		start := time.Now()
		spec03URL := baseURL + "/spec03"
		card, err := agentcard.DefaultResolver.Resolve(ctx, spec03URL)
		if err != nil {
			record("v03/spec03-send-message", "v0.3 Send Message", false,
				fmt.Sprintf("card resolve error (SDK may not support v0.3): %v", err), time.Since(start))
		} else {
			v03Client, cErr := a2aclient.NewFromCard(ctx, card)
			if cErr != nil {
				record("v03/spec03-send-message", "v0.3 Send Message", false,
					fmt.Sprintf("client create error (SDK may not support v0.3): %v", cErr), time.Since(start))
			} else {
				msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only hello"))
				resp, sErr := v03Client.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
				dur := time.Since(start)
				v03Client.Destroy()
				if sErr != nil {
					record("v03/spec03-send-message", "v0.3 Send Message", false,
						fmt.Sprintf("send error (SDK may not support v0.3): %v", sErr), dur)
				} else {
					text := extractResultText(resp)
					record("v03/spec03-send-message", "v0.3 Send Message", true,
						fmt.Sprintf("response=%s", truncate(text, 120)), dur)
				}
			}
		}
	}

	// v03/spec03-task-lifecycle — SDK task lifecycle on v0.3 agent
	{
		start := time.Now()
		spec03URL := baseURL + "/spec03"
		card, err := agentcard.DefaultResolver.Resolve(ctx, spec03URL)
		if err != nil {
			record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
				fmt.Sprintf("card resolve error (SDK may not support v0.3): %v", err), time.Since(start))
		} else {
			v03Client, cErr := a2aclient.NewFromCard(ctx, card)
			if cErr != nil {
				record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
					fmt.Sprintf("client create error (SDK may not support v0.3): %v", cErr), time.Since(start))
			} else {
				msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle process"))
				resp, sErr := v03Client.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
				dur := time.Since(start)
				v03Client.Destroy()
				if sErr != nil {
					record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
						fmt.Sprintf("send error (SDK may not support v0.3): %v", sErr), dur)
				} else {
					switch v := resp.(type) {
					case *a2a.Task:
						passed := v.Status.State == a2a.TaskStateCompleted
						record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", passed,
							fmt.Sprintf("state=%s, artifacts=%d, id=%s", v.Status.State, len(v.Artifacts), v.ID), dur)
					case *a2a.Message:
						record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
							"expected Task, got Message", dur)
					default:
						record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
							fmt.Sprintf("unexpected type %T", resp), dur)
					}
				}
			}
		}
	}

	// v03/spec03-streaming — SDK streaming on v0.3 agent
	{
		start := time.Now()
		spec03URL := baseURL + "/spec03"
		card, err := agentcard.DefaultResolver.Resolve(ctx, spec03URL)
		if err != nil {
			record("v03/spec03-streaming", "v0.3 Streaming", false,
				fmt.Sprintf("card resolve error (SDK may not support v0.3): %v", err), time.Since(start))
		} else {
			v03Client, cErr := a2aclient.NewFromCard(ctx, card)
			if cErr != nil {
				record("v03/spec03-streaming", "v0.3 Streaming", false,
					fmt.Sprintf("client create error (SDK may not support v0.3): %v", cErr), time.Since(start))
			} else {
				msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("streaming generate"))
				eventCount := 0
				var lastState a2a.TaskState
				var lastHasArtifact bool
				var streamErr error
				for event, sErr := range v03Client.SendStreamingMessage(ctx, &a2a.SendMessageRequest{Message: msg}) {
					if sErr != nil {
						streamErr = sErr
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
				v03Client.Destroy()
				if streamErr != nil {
					record("v03/spec03-streaming", "v0.3 Streaming", false,
						fmt.Sprintf("stream error (SDK may not support v0.3 streaming): %v", streamErr), dur)
				} else {
					passed := eventCount > 1 && (lastState == a2a.TaskStateCompleted || lastHasArtifact)
					record("v03/spec03-streaming", "v0.3 Streaming", passed,
						fmt.Sprintf("events=%d, lastState=%s, hasArtifact=%v", eventCount, lastState, lastHasArtifact), dur)
				}
			}
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
		SDK:             detectSDKSource(),
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
