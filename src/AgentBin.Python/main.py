"""AgentBin Python A2A Server - Main entry point."""

import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route, Mount

from a2a.server.apps import A2AStarletteApplication
from a2a.server.apps.rest import A2ARESTFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

from cards import build_spec_card, build_extended_spec_card, build_echo_card, card_to_wire_dict
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

    spec_card_dict = card_to_wire_dict(spec_card, base_url, "/spec")
    extended_spec_card_dict = card_to_wire_dict(extended_spec_card, base_url, "/spec")
    echo_card_dict = card_to_wire_dict(echo_card, base_url, "/echo")

    # Shared task stores (one per agent)
    spec_task_store = InMemoryTaskStore()
    echo_task_store = InMemoryTaskStore()

    # JSON-RPC handler for SpecAgent
    spec_handler = DefaultRequestHandler(
        agent_executor=SpecAgent(),
        task_store=spec_task_store,
    )
    spec_jsonrpc = A2AStarletteApplication(
        agent_card=spec_card,
        http_handler=spec_handler,
        extended_agent_card=extended_spec_card,
    )

    # JSON-RPC handler for EchoAgent
    echo_handler = DefaultRequestHandler(
        agent_executor=EchoAgent(),
        task_store=echo_task_store,
    )
    echo_jsonrpc = A2AStarletteApplication(
        agent_card=echo_card,
        http_handler=echo_handler,
    )

    # REST handler for SpecAgent
    spec_rest_handler = DefaultRequestHandler(
        agent_executor=SpecAgent(),
        task_store=spec_task_store,
    )
    spec_rest = A2ARESTFastAPIApplication(
        agent_card=spec_card,
        http_handler=spec_rest_handler,
        extended_agent_card=extended_spec_card,
    )
    spec_rest_app = spec_rest.build()

    # REST handler for EchoAgent
    echo_rest_handler = DefaultRequestHandler(
        agent_executor=EchoAgent(),
        task_store=echo_task_store,
    )
    echo_rest = A2ARESTFastAPIApplication(
        agent_card=echo_card,
        http_handler=echo_rest_handler,
    )
    echo_rest_app = echo_rest.build()

    # Custom card endpoints (serve proper wire-format JSON)
    async def spec_agent_card(request: Request) -> JSONResponse:
        return JSONResponse(spec_card_dict)

    async def echo_agent_card(request: Request) -> JSONResponse:
        return JSONResponse(echo_card_dict)

    async def root_agent_card(request: Request) -> JSONResponse:
        return JSONResponse(spec_card_dict)

    async def spec_extended_card(request: Request) -> JSONResponse:
        return JSONResponse(extended_spec_card_dict)

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    async def root(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            "AgentBin Python Server\n"
            "Agents: /spec, /echo\n"
            "Health: /health\n"
        )

    # Build routes: explicit card routes first (no Mounts yet)
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/", root, methods=["GET"]),
        Route("/.well-known/agent-card.json", root_agent_card, methods=["GET"]),
        Route("/spec/.well-known/agent-card.json", spec_agent_card, methods=["GET"]),
        Route("/spec/extended-agent-card", spec_extended_card, methods=["GET"]),
        Route("/echo/.well-known/agent-card.json", echo_agent_card, methods=["GET"]),
    ]

    app = Starlette(routes=routes)

    # Add JSON-RPC routes directly (POST /spec, POST /echo) — avoids 307 redirect from Mount
    spec_jsonrpc.add_routes_to_app(app, rpc_url="/spec", agent_card_url="/spec/.well-known/agent-card.json")
    echo_jsonrpc.add_routes_to_app(app, rpc_url="/echo", agent_card_url="/echo/.well-known/agent-card.json")

    # Add REST sub-apps AFTER JSON-RPC routes so exact Route matches take priority over Mount
    app.routes.append(Mount("/spec", spec_rest_app))
    app.routes.append(Mount("/echo", echo_rest_app))

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
