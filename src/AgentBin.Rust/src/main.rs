mod echo_agent;
mod spec_agent;

use std::env;
use std::sync::{Arc, OnceLock};
use axum::{
    Router,
    routing::get,
    http::Method,
    response::Json,
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

    // Pre-compute the spec agent card for root /.well-known discovery.
    // The TCK and some clients fetch the card via urljoin(sut_url, "/.well-known/agent-card.json")
    // which resolves to the host root, not the nested /spec prefix.
    let root_spec_card = spec_handler.agent_card(&base_url);
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

    let spec_router = spec_server.build_router();
    let echo_router = echo_server.build_router();

    // Serve the spec agent card at the host root /.well-known paths so
    // clients that resolve /.well-known/* relative to the host (e.g. the
    // A2A TCK via urljoin) can discover it. Matches .NET/Go/Python behavior.
    let root_card = Arc::new(root_spec_card);
    let card_get = {
        let card = root_card.clone();
        move || {
            let card = card.clone();
            async move { Json((*card).clone()) }
        }
    };

    let app = Router::new()
        .route("/.well-known/agent-card.json", get(card_get.clone()))
        .route("/.well-known/agent.json", get(card_get))
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
