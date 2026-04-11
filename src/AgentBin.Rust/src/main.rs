mod echo_agent;
mod spec_agent;

use std::env;
use std::sync::{Arc, OnceLock};
use axum::{
    Router,
    routing::get,
    http::Method,
};
use tower_http::cors::{CorsLayer, Any};
use a2a_rs_server::{A2aServer, MessageHandler};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"))
        )
        .init();

    let port = env::var("PORT").unwrap_or_else(|_| "5000".to_string());
    let base_url = env::var("BASE_URL")
        .unwrap_or_else(|_| format!("http://localhost:{}", port));

    tracing::info!("Starting AgentBin Rust Server on port {}", port);

    let spec_event_tx = Arc::new(OnceLock::new());
    let spec_handler = spec_agent::SpecAgent::new("/spec", spec_event_tx.clone());
    let echo_handler = echo_agent::EchoAgent::new("/echo");

    let _spec_card = spec_handler.agent_card(&format!("{}/spec", base_url));
    let _echo_card = echo_handler.agent_card(&format!("{}/echo", base_url));

    let spec_server = A2aServer::new(spec_handler)
        .bind_unchecked(&format!("127.0.0.1:{}", port));
    // Fill the event_tx slot before build_router() consumes the server
    let _ = spec_event_tx.set(spec_server.get_event_sender());
    
    let echo_server = A2aServer::new(echo_handler)
        .bind_unchecked(&format!("127.0.0.1:{}", port));

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(Any);

    let spec_router = spec_server.build_router()
        .route("/", get(|| async {
            "AgentBin Spec Agent (Rust)\nAgent card: /.well-known/agent-card.json\nJSONRPC: POST /v1/rpc"
        }));

    let echo_router = echo_server.build_router()
        .route("/", get(|| async {
            "AgentBin Echo Agent (Rust)\nAgent card: /.well-known/agent-card.json\nJSONRPC: POST /v1/rpc"
        }));

    let app = Router::new()
        .nest("/spec", spec_router)
        .nest("/echo", echo_router)
        .route("/health", get(|| async { "OK" }))
        .route("/", get(|| async {
            "AgentBin Rust Server\nAgents: /spec, /echo\nHealth: /health\n"
        }))
        .layer(cors);

    let bind_addr = format!("0.0.0.0:{}", port);
    tracing::info!("Server listening on http://{}", bind_addr);
    tracing::info!("Spec agent: {}/spec", base_url);
    tracing::info!("Echo agent: {}/echo", base_url);
    tracing::info!("Health: {}/health", base_url);

    let listener = tokio::net::TcpListener::bind(&bind_addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
