package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/a2aproject/a2a-go/a2a"
	"github.com/a2aproject/a2a-go/a2aclient"
	"github.com/a2aproject/a2a-go/a2aclient/agentcard"
)

const baseURL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"

type result struct {
	name   string
	pass   bool
	detail string
}

var results []result

func record(name string, pass bool, detail string) {
	results = append(results, result{name, pass, detail})
	status := "PASS"
	if !pass {
		status = "FAIL"
	}
	fmt.Printf("  [%s] %s — %s\n", status, name, detail)
}

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	fmt.Println("=== Go A2A Client Test against Azure-deployed agentbin ===")
	fmt.Printf("Base URL: %s\n\n", baseURL)

	// ---- Test 1: Resolve echo agent card ----
	fmt.Println("--- Agent Card Resolution ---")
	echoCard, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/echo")
	if err != nil {
		record("echo-card-resolve", false, fmt.Sprintf("error: %v", err))
	} else {
		record("echo-card-resolve", true, fmt.Sprintf("name=%q, skills=%d, interfaces=%d",
			echoCard.Name, len(echoCard.Skills), len(echoCard.SupportedInterfaces)))
	}

	// ---- Test 2: Resolve spec agent card ----
	specCard, err := agentcard.DefaultResolver.Resolve(ctx, baseURL+"/spec")
	if err != nil {
		record("spec-card-resolve", false, fmt.Sprintf("error: %v", err))
	} else {
		record("spec-card-resolve", true, fmt.Sprintf("name=%q, skills=%d, interfaces=%d",
			specCard.Name, len(specCard.Skills), len(specCard.SupportedInterfaces)))
	}

	// ---- Test 3: Send message to echo agent via SDK ----
	fmt.Println("\n--- Echo Agent (SDK client) ---")
	if echoCard != nil {
		echoClient, err := a2aclient.NewFromCard(ctx, echoCard)
		if err != nil {
			record("echo-sdk-send", false, fmt.Sprintf("client creation error: %v", err))
		} else {
			defer echoClient.Destroy()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hello from Go SDK"))
			resp, err := echoClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				record("echo-sdk-send", false, fmt.Sprintf("error: %v", err))
			} else {
				detail := describeResult(resp)
				record("echo-sdk-send", true, detail)
			}
		}
	} else {
		record("echo-sdk-send", false, "skipped — no card")
	}

	// ---- Test 4: Send message-only to spec agent via SDK ----
	fmt.Println("\n--- Spec Agent: message-only (SDK client) ---")
	if specCard != nil {
		specClient, err := a2aclient.NewFromCard(ctx, specCard)
		if err != nil {
			record("spec-sdk-message-only", false, fmt.Sprintf("client creation error: %v", err))
		} else {
			defer specClient.Destroy()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("message-only hello from Go SDK"))
			resp, err := specClient.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				record("spec-sdk-message-only", false, fmt.Sprintf("error: %v", err))
			} else {
				detail := describeResult(resp)
				record("spec-sdk-message-only", true, detail)
			}
		}
	} else {
		record("spec-sdk-message-only", false, "skipped — no card")
	}

	// ---- Test 5: Send task-lifecycle to spec agent via SDK ----
	fmt.Println("\n--- Spec Agent: task-lifecycle (SDK client) ---")
	if specCard != nil {
		specClient2, err := a2aclient.NewFromCard(ctx, specCard)
		if err != nil {
			record("spec-sdk-task-lifecycle", false, fmt.Sprintf("client creation error: %v", err))
		} else {
			defer specClient2.Destroy()
			msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("task-lifecycle hello from Go SDK"))
			resp, err := specClient2.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
			if err != nil {
				record("spec-sdk-task-lifecycle", false, fmt.Sprintf("error: %v", err))
			} else {
				detail := describeResult(resp)
				record("spec-sdk-task-lifecycle", true, detail)
			}
		}
	} else {
		record("spec-sdk-task-lifecycle", false, "skipped — no card")
	}

	// ---- Test 6: Raw HTTP fallback to echo agent ----
	fmt.Println("\n--- Echo Agent (raw HTTP) ---")
	rawBody := `{"jsonrpc":"2.0","method":"SendMessage","id":"raw-1","params":{"message":{"messageId":"raw-msg-1","role":"ROLE_USER","parts":[{"content":"hello from raw HTTP","mediaType":"text/plain"}]}}}`
	httpResp, err := http.Post(baseURL+"/echo", "application/json", strings.NewReader(rawBody))
	if err != nil {
		record("echo-raw-http", false, fmt.Sprintf("error: %v", err))
	} else {
		defer httpResp.Body.Close()
		var respJSON map[string]any
		if err := json.NewDecoder(httpResp.Body).Decode(&respJSON); err != nil {
			record("echo-raw-http", false, fmt.Sprintf("decode error: %v", err))
		} else {
			if respJSON["error"] != nil {
				record("echo-raw-http", false, fmt.Sprintf("JSON-RPC error: %v", respJSON["error"]))
			} else {
				b, _ := json.Marshal(respJSON["result"])
				detail := string(b)
				if len(detail) > 200 {
					detail = detail[:200] + "..."
				}
				record("echo-raw-http", true, detail)
			}
		}
	}

	// ---- Summary ----
	fmt.Println("\n========================================")
	fmt.Println("          SUMMARY")
	fmt.Println("========================================")
	passed, failed := 0, 0
	for _, r := range results {
		status := "PASS"
		if !r.pass {
			status = "FAIL"
			failed++
		} else {
			passed++
		}
		fmt.Printf("  [%s] %-30s %s\n", status, r.name, r.detail)
	}
	fmt.Printf("\nTotal: %d passed, %d failed out of %d\n", passed, failed, len(results))

	if failed > 0 {
		os.Exit(1)
	}
}

func describeResult(resp a2a.SendMessageResult) string {
	switch v := resp.(type) {
	case *a2a.Message:
		text := extractText(v.Parts)
		return fmt.Sprintf("Message(role=%s, text=%q)", v.Role, truncate(text, 100))
	case *a2a.Task:
		text := ""
		if v.Status.Message != nil {
			text = extractText(v.Status.Message.Parts)
		}
		return fmt.Sprintf("Task(id=%s, state=%s, text=%q)", v.ID, v.Status.State, truncate(text, 100))
	default:
		return fmt.Sprintf("unknown type %T", resp)
	}
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

func truncate(s string, max int) string {
	if len(s) > max {
		return s[:max] + "..."
	}
	return s
}
