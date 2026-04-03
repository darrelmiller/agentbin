package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

func main() {
	port := getEnv("PORT", "5000")
	baseURL := getEnv("BASE_URL", fmt.Sprintf("http://localhost:%s", port))

	specCard := buildSpecCard(baseURL)
	echoCard := buildEchoCard(baseURL)
	extendedSpecCard := buildExtendedSpecCard(baseURL)

	// Spec agent handler (with streaming + extended card)
	specExecutor := &specAgent{}
	specHandler := a2asrv.NewHandler(specExecutor,
		a2asrv.WithCapabilityChecks(&a2a.AgentCapabilities{Streaming: true, ExtendedAgentCard: true}),
		a2asrv.WithExtendedAgentCard(extendedSpecCard),
	)

	// Echo agent handler
	echoExecutor := &echoAgent{}
	echoHandler := a2asrv.NewHandler(echoExecutor)

	mux := http.NewServeMux()

	// Health
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "OK")
	})

	// Spec agent — JSONRPC at /spec, REST at /spec/v1/...
	specREST := http.StripPrefix("/spec", a2asrv.NewRESTHandler(specHandler))
	specJSONRPC := a2asrv.NewJSONRPCHandler(specHandler)
	specCardHandler := a2asrv.NewStaticAgentCardHandler(specCard)
	mux.HandleFunc("/spec", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			specJSONRPC.ServeHTTP(w, r)
		} else {
			handleAgentInfo("AgentBin Spec Agent (Go)", specCard)(w, r)
		}
	})
	mux.Handle("GET /spec/.well-known/agent-card.json", specCardHandler)
	mux.Handle("/spec/", specREST)

	// Echo agent — JSONRPC at /echo, REST at /echo/v1/...
	echoREST := http.StripPrefix("/echo", a2asrv.NewRESTHandler(echoHandler))
	echoJSONRPC := a2asrv.NewJSONRPCHandler(echoHandler)
	echoCardHandler := a2asrv.NewStaticAgentCardHandler(echoCard)
	mux.HandleFunc("/echo", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			echoJSONRPC.ServeHTTP(w, r)
		} else {
			handleAgentInfo("AgentBin Echo Agent (Go)", echoCard)(w, r)
		}
	})
	mux.Handle("GET /echo/.well-known/agent-card.json", echoCardHandler)
	mux.Handle("/echo/", echoREST)

	// Default agent card at well-known root
	mux.Handle("GET /.well-known/agent-card.json", specCardHandler)

	// Root info
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprintf(w, "AgentBin Go Server\nAgents: /spec, /echo\nHealth: /health\n")
	})

	handler := corsMiddleware(mux)

	log.Printf("AgentBin Go server starting on port %s (base URL: %s)", port, baseURL)
	if err := http.ListenAndServe(":"+port, handler); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, A2A-Version")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func handleAgentInfo(title string, card *a2a.AgentCard) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprintf(w, "%s\nSkills: %d\n", title, len(card.Skills))
		for _, s := range card.Skills {
			fmt.Fprintf(w, "  - %s: %s\n", s.ID, s.Description)
		}
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
