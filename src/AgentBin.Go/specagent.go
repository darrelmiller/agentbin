package main

import (
	"context"
	"fmt"
	"iter"
	"strings"
	"time"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

type specAgent struct{}

var _ a2asrv.AgentExecutor = (*specAgent)(nil)

func (s *specAgent) Execute(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	// Multi-turn continuation
	if execCtx.StoredTask != nil && execCtx.StoredTask.Status.State == a2a.TaskStateInputRequired {
		return s.handleMultiTurnContinuation(ctx, execCtx)
	}

	text := extractText(execCtx.Message)
	keyword, _ := splitKeyword(text)

	switch keyword {
	case "message-only":
		return s.handleMessageOnly(ctx, execCtx, text)
	case "task-lifecycle":
		return s.handleTaskLifecycle(ctx, execCtx, text)
	case "task-failure":
		return s.handleTaskFailure(ctx, execCtx, text)
	case "task-cancel":
		return s.handleTaskCancel(ctx, execCtx)
	case "multi-turn":
		return s.handleMultiTurn(ctx, execCtx, text)
	case "streaming":
		return s.handleStreaming(ctx, execCtx)
	case "long-running":
		return s.handleLongRunning(ctx, execCtx)
	case "data-types":
		return s.handleDataTypes(ctx, execCtx, text)
	default:
		return s.handleHelp(ctx, execCtx)
	}
}

func (s *specAgent) Cancel(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		msg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[task-cancel] Task canceled by client request."))
		evt := a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCanceled, msg)
		if execCtx.Metadata != nil {
			evt.Metadata = execCtx.Metadata
		}
		yield(evt, nil)
	}
}

// --- message-only: no task, just a message response ---

func (s *specAgent) handleMessageOnly(_ context.Context, _ *a2asrv.ExecutorContext, text string) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		reply := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart(fmt.Sprintf("[message-only] You said: %s", text)))
		yield(reply, nil)
	}
}

// --- task-lifecycle: submitted → working → completed ---

func (s *specAgent) handleTaskLifecycle(_ context.Context, execCtx *a2asrv.ExecutorContext, text string) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		// Submitted task
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}

		// Working
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, nil), nil) {
			return
		}

		// Artifact
		if !yield(newArtifact(execCtx, "result", "The processed result", "",
			a2a.NewTextPart(fmt.Sprintf("[task-lifecycle] Processed: %s", text))), nil) {
			return
		}

		// Complete
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, nil), nil)
	}
}

// --- task-failure: submitted → working → failed ---

func (s *specAgent) handleTaskFailure(_ context.Context, execCtx *a2asrv.ExecutorContext, _ string) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, nil), nil) {
			return
		}

		failMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[task-failure] Simulated failure: this task was designed to fail for testing purposes."))
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateFailed, failMsg), nil)
	}
}

// --- task-cancel: submitted → working → wait for cancel ---

func (s *specAgent) handleTaskCancel(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}

		workMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[task-cancel] Working... send a cancel request to this task."))
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, workMsg), nil) {
			return
		}

		// Wait for cancellation or timeout
		select {
		case <-ctx.Done():
			return // canceled — Cancel() handles the response
		case <-time.After(30 * time.Second):
			doneMsg := a2a.NewMessage(a2a.MessageRoleAgent,
				a2a.NewTextPart("[task-cancel] No cancel received within timeout. Completed normally."))
			yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, doneMsg), nil)
		}
	}
}

// --- multi-turn: input-required flow ---

func (s *specAgent) handleMultiTurn(_ context.Context, execCtx *a2asrv.ExecutorContext, text string) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}

		// First turn: emit artifact + request input
		if !yield(newArtifact(execCtx, "turn-1", "turn-1", "",
			a2a.NewTextPart(fmt.Sprintf("[multi-turn] Received initial message: %s", text))), nil) {
			return
		}

		promptMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[multi-turn] Please send a follow-up message to continue. Say 'done' to complete."))
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateInputRequired, promptMsg), nil)
	}
}

func (s *specAgent) handleMultiTurnContinuation(_ context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	text := extractText(execCtx.Message)
	isDone := strings.Contains(strings.ToLower(text), "done")

	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, nil), nil) {
			return
		}

		if isDone {
			if !yield(newArtifact(execCtx, "final", "final", "",
				a2a.NewTextPart(fmt.Sprintf("[multi-turn] Final message received: %s", text))), nil) {
				return
			}
			doneMsg := a2a.NewMessage(a2a.MessageRoleAgent,
				a2a.NewTextPart("[multi-turn] Conversation complete. All turns processed successfully."))
			yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, doneMsg), nil)
		} else {
			turnID := fmt.Sprintf("turn-%d", time.Now().UnixNano())
			if !yield(newArtifact(execCtx, turnID, turnID, "",
				a2a.NewTextPart(fmt.Sprintf("[multi-turn] Continuation received: %s", text))), nil) {
				return
			}
			promptMsg := a2a.NewMessage(a2a.MessageRoleAgent,
				a2a.NewTextPart("[multi-turn] Got it. Send another message, or say 'done' to complete."))
			yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateInputRequired, promptMsg), nil)
		}
	}
}

// --- streaming: SSE with multiple chunks ---

func (s *specAgent) handleStreaming(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}

		startMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[streaming] Starting streamed response..."))
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, startMsg), nil) {
			return
		}

		chunks := []string{
			"[streaming] Chunk 1: Processing your request...",
			"[streaming] Chunk 2: Analyzing input data...",
			"[streaming] Chunk 3: Generating results...",
			"[streaming] Chunk 4: Finalizing output...",
		}

		for i, chunk := range chunks {
			if i > 0 {
				select {
				case <-ctx.Done():
					return
				case <-time.After(500 * time.Millisecond):
				}
			}

			evt := &a2a.TaskArtifactUpdateEvent{
				TaskID:    execCtx.TaskID,
				ContextID: execCtx.ContextID,
				Append:    i > 0,
				LastChunk: i == len(chunks)-1,
				Artifact: &a2a.Artifact{
					ID:   "stream-result",
					Name: "Streamed Result",
					Parts: []*a2a.Part{
						a2a.NewTextPart(chunk),
					},
				},
			}
			if !yield(evt, nil) {
				return
			}
		}

		doneMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[streaming] Stream complete. 4 chunks delivered."))
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, doneMsg), nil)
	}
}

// --- long-running: periodic status updates ---

func (s *specAgent) handleLongRunning(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}

		for i := 1; i <= 5; i++ {
			statusMsg := a2a.NewMessage(a2a.MessageRoleAgent,
				a2a.NewTextPart(fmt.Sprintf("[long-running] Step %d/5: Processing...", i)))
			if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, statusMsg), nil) {
				return
			}

			if !yield(newArtifact(execCtx,
				fmt.Sprintf("step-%d", i),
				fmt.Sprintf("step-%d", i), "",
				a2a.NewTextPart(fmt.Sprintf("[long-running] Step %d result: completed at %s", i, time.Now().UTC().Format(time.RFC3339)))), nil) {
				return
			}

			if i < 5 {
				select {
				case <-ctx.Done():
					return
				case <-time.After(2 * time.Second):
				}
			}
		}

		doneMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[long-running] All 5 steps complete."))
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, doneMsg), nil)
	}
}

// --- data-types: text, JSON, file, multi-part artifacts ---

func (s *specAgent) handleDataTypes(_ context.Context, execCtx *a2asrv.ExecutorContext, text string) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
			return
		}
		if !yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateWorking, nil), nil) {
			return
		}

		// 1. Text artifact
		if !yield(newArtifact(execCtx, "text-artifact", "Text Artifact", "A simple text artifact",
			a2a.NewTextPart("[data-types] This is a plain text artifact.")), nil) {
			return
		}

		// 2. JSON data artifact
		jsonData := map[string]any{
			"type":      "test-result",
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"input":     text,
			"metrics": map[string]any{
				"latencyMs":       42,
				"tokensProcessed": 7,
			},
		}
		if !yield(newArtifact(execCtx, "data-artifact", "Structured Data Artifact", "A structured JSON data artifact",
			a2a.NewDataPart(jsonData)), nil) {
			return
		}

		// 3. File artifact (SVG)
		svgContent := `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <circle cx="50" cy="50" r="40" fill="#4CAF50"/>
  <text x="50" y="55" text-anchor="middle" fill="white" font-size="14">A2A</text>
</svg>`
		filePart := a2a.NewRawPart([]byte(svgContent))
		filePart.MediaType = "image/svg+xml"
		if !yield(newArtifact(execCtx, "file-artifact", "File Artifact", "A binary file artifact (SVG image)",
			filePart), nil) {
			return
		}

		// 4. Multi-part artifact
		multiEvt := &a2a.TaskArtifactUpdateEvent{
			TaskID:    execCtx.TaskID,
			ContextID: execCtx.ContextID,
			Artifact: &a2a.Artifact{
				ID:          "multi-part-artifact",
				Name:        "Multi-Part Artifact",
				Description: "An artifact containing both text and structured data parts",
				Parts: []*a2a.Part{
					a2a.NewTextPart("[data-types] This artifact has multiple parts."),
					a2a.NewDataPart(map[string]any{"multiPart": true, "partCount": 2}),
				},
			},
		}
		if !yield(multiEvt, nil) {
			return
		}

		doneMsg := a2a.NewMessage(a2a.MessageRoleAgent,
			a2a.NewTextPart("[data-types] Generated 4 artifacts with different content types: text, JSON data, file (SVG), and multi-part."))
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCompleted, doneMsg), nil)
	}
}

// --- default: help message ---

func (s *specAgent) handleHelp(_ context.Context, _ *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	helpText := `AgentBin Spec Agent — A2A v1.0 Test Bed

Send a message starting with one of these skill keywords:

  message-only    → Stateless message response (no task)
  task-lifecycle  → Full task: submitted → working → completed
  task-failure    → Task that fails with error message
  task-cancel     → Task that waits to be canceled
  multi-turn      → Multi-turn conversation (input-required)
  streaming       → Streamed response with multiple chunks
  long-running    → Long-running task with periodic updates
  data-types      → Mixed content: text, JSON, file, multi-part

Example: "task-lifecycle hello world"`

	return func(yield func(a2a.Event, error) bool) {
		yield(a2a.NewMessage(a2a.MessageRoleAgent, a2a.NewTextPart(helpText)), nil)
	}
}

// --- helpers ---

func newArtifact(execCtx *a2asrv.ExecutorContext, id, name, desc string, parts ...*a2a.Part) *a2a.TaskArtifactUpdateEvent {
	return &a2a.TaskArtifactUpdateEvent{
		TaskID:    execCtx.TaskID,
		ContextID: execCtx.ContextID,
		Artifact: &a2a.Artifact{
			ID:          a2a.ArtifactID(id),
			Name:        name,
			Description: desc,
			Parts:       parts,
		},
	}
}

func extractText(msg *a2a.Message) string {
	if msg == nil {
		return ""
	}
	for _, part := range msg.Parts {
		if t, ok := part.Content.(a2a.Text); ok {
			return string(t)
		}
	}
	return ""
}

func splitKeyword(text string) (keyword, rest string) {
	lower := strings.ToLower(strings.TrimSpace(text))
	parts := strings.SplitN(lower, " ", 2)
	keyword = parts[0]
	if len(parts) > 1 {
		rest = parts[1]
	}
	return
}
