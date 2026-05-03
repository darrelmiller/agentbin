#!/bin/bash
# post-create.sh — Restores dependencies for all AgentBin server and client projects.
# Runs automatically when the devcontainer is created.
#
# Compatible with both Docker and Podman (rootless) container runtimes.
# NOTE: Swift client tests require macOS and are excluded from the devcontainer.

set -e

# Ensure we're in the workspace root (handles both /workspaces/<repo> conventions)
WORKSPACE_ROOT="${PWD}"
if [ -f "/workspaces/agentbin/agentbin.sln" ]; then
  WORKSPACE_ROOT="/workspaces/agentbin"
fi
cd "$WORKSPACE_ROOT"

echo "==> Restoring .NET projects..."
dotnet restore agentbin.sln

echo "==> Installing Python server dependencies..."
pip install --user -r src/AgentBin.Python/requirements.txt

echo "==> Installing Python client dependencies..."
pip install --user -r tests/ClientTests/python/requirements.txt

echo "==> Installing JS client dependencies..."
cd tests/ClientTests/js && npm install && cd "$WORKSPACE_ROOT"

echo "==> Building Java server..."
cd src/AgentBin.Java && mvn package -DskipTests -q && cd "$WORKSPACE_ROOT"

echo "==> Building Java client..."
cd tests/ClientTests/java && mvn package -DskipTests -q && cd "$WORKSPACE_ROOT"

echo "==> Fetching Go dependencies..."
cd src/AgentBin.Go && go mod download && cd "$WORKSPACE_ROOT"
cd tests/ClientTests/go && go mod download && cd "$WORKSPACE_ROOT"

echo "==> Fetching Rust dependencies..."
cd src/AgentBin.Rust && cargo fetch --quiet && cd "$WORKSPACE_ROOT"
cd tests/ClientTests/rust && cargo fetch --quiet && cd "$WORKSPACE_ROOT"

echo "==> Cloning and setting up A2A TCK..."
TCK_DIR="/workspaces/a2a-tck"
if [ -d "$TCK_DIR" ]; then
  echo "    TCK already cloned, pulling latest..."
  cd "$TCK_DIR" && git pull --ff-only || true
else
  git clone https://github.com/a2aproject/a2a-tck "$TCK_DIR"
fi
cd "$TCK_DIR" && python -m venv .venv && .venv/bin/pip install -q -e . && cd "$WORKSPACE_ROOT"

# Ensure PATH includes user-local pip installs (Podman rootless)
if ! grep -q 'A2A_TCK_ROOT' ~/.bashrc 2>/dev/null; then
  echo 'export A2A_TCK_ROOT=/workspaces/a2a-tck' >> ~/.bashrc
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi

echo "==> Done! All dependencies restored."
