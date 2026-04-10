"""AgentBin Python A2A Server - Main entry point."""

import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route, Mount

from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

from cards import build_spec_card, build_extended_spec_card, build_echo_card
from spec_agent import SpecAgent
from echo_agent import EchoAgent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AgentBin.Python")


def create_app() -> Starlette:
    port = int(os.getenv("PORT", "5000"))
    base_url = os.getenv("BASE_URL", f"http://localhost:{port}")

    spec_card = build_spec_card(base_url)
    extended_spec_card = build_extended_spec_card(base_url)
    echo_card = build_echo_card(base_url)

    # Shared task stores (one per agent)
    spec_task_store = InMemoryTaskStore()
    echo_task_store = InMemoryTaskStore()

    # Request handlers (V2 API takes agent_card)
    spec_handler = DefaultRequestHandlerV2(
        agent_executor=SpecAgent(),
        task_store=spec_task_store,
        agent_card=spec_card,
        extended_agent_card=extended_spec_card,
    )
    echo_handler = DefaultRequestHandlerV2(
        agent_executor=EchoAgent(),
        task_store=echo_task_store,
        agent_card=echo_card,
    )

    # Build routes
    routes = [
        Route("/health", lambda r: PlainTextResponse("OK"), methods=["GET"]),
        Route("/", lambda r: PlainTextResponse(
            "AgentBin Python Server\nAgents: /spec, /echo\nHealth: /health\n"
        ), methods=["GET"]),
    ]

    # Agent card routes
    routes.extend(create_agent_card_routes(spec_card, card_url="/.well-known/agent-card.json"))
    routes.extend(create_agent_card_routes(spec_card, card_url="/spec/.well-known/agent-card.json"))
    routes.extend(create_agent_card_routes(echo_card, card_url="/echo/.well-known/agent-card.json"))

    # Extended agent card route (custom handler that requires auth)
    async def spec_extended_card(request: Request) -> JSONResponse:
        from a2a.server.routes.agent_card_routes import agent_card_to_dict
        return JSONResponse(agent_card_to_dict(extended_spec_card))

    routes.append(Route("/spec/extended-agent-card", spec_extended_card, methods=["GET"]))

    # JSON-RPC routes
    routes.extend(create_jsonrpc_routes(spec_handler, rpc_url="/spec"))
    routes.extend(create_jsonrpc_routes(echo_handler, rpc_url="/echo"))

    app = Starlette(routes=routes)

    # REST routes (mounted as sub-apps)
    spec_rest_routes = create_rest_routes(spec_handler, path_prefix="/spec")
    echo_rest_routes = create_rest_routes(echo_handler, path_prefix="/echo")
    for r in spec_rest_routes:
        app.routes.append(r)
    for r in echo_rest_routes:
        app.routes.append(r)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "A2A-Version"],
    )

    return app


def main():
    port = int(os.getenv("PORT", "5000"))
    base_url = os.getenv("BASE_URL", f"http://localhost:{port}")
    logger.info(f"AgentBin Python server starting on port {port} (base URL: {base_url})")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
