#!/bin/bash
# post-create.sh — Restores dependencies for all AgentBin server and client projects.
# Runs automatically when the devcontainer is created.
#
# NOTE: Swift client tests require macOS and are excluded from the devcontainer.

set -e

echo "==> Restoring .NET projects..."
dotnet restore agentbin.sln

echo "==> Installing Python server dependencies..."
pip install -r src/AgentBin.Python/requirements.txt

echo "==> Installing Python client dependencies..."
pip install -r tests/ClientTests/python/requirements.txt

echo "==> Installing JS client dependencies..."
cd tests/ClientTests/js && npm install && cd -

echo "==> Building Java server..."
cd src/AgentBin.Java && mvn package -DskipTests && cd -

echo "==> Building Java client..."
cd tests/ClientTests/java && mvn package -DskipTests && cd -

echo "==> Fetching Go dependencies..."
cd src/AgentBin.Go && go mod download && cd -
cd tests/ClientTests/go && go mod download && cd -

echo "==> Fetching Rust dependencies..."
cd src/AgentBin.Rust && cargo fetch && cd -
cd tests/ClientTests/rust && cargo fetch && cd -

echo "==> Cloning and setting up A2A TCK..."
git clone https://github.com/a2aproject/a2a-tck /workspaces/a2a-tck
cd /workspaces/a2a-tck && python -m venv .venv && .venv/bin/pip install -e . && cd -

echo 'export A2A_TCK_ROOT=/workspaces/a2a-tck' >> ~/.bashrc

echo "==> Done! All dependencies restored."
