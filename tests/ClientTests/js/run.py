#!/usr/bin/env python3
"""
Standalone runner for JS/TypeScript A2A SDK client tests.

Usage:
    python run.py [base_url]

If no base_url is provided, the default AgentBin URL is used.
Runs `npm install` if node_modules is missing, then executes
the test suite and prints a summary.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL

    # Ensure UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Install dependencies if node_modules is missing
    node_modules = SCRIPT_DIR / "node_modules"
    if not node_modules.exists():
        print("  node_modules not found — running npm install...")
        npm_result = subprocess.run(
            ["npm", "install"],
            cwd=str(SCRIPT_DIR),
            shell=(sys.platform == "win32"),
        )
        if npm_result.returncode != 0:
            print("  ✗ npm install failed")
            sys.exit(1)
        print()

    # Run the test suite
    cmd = ["node", "test_js_client.mjs", base_url]
    print(f"  Running: {' '.join(cmd)}")
    print(f"  Base URL: {base_url}")
    print()

    use_shell = sys.platform == "win32"
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR), shell=use_shell)

    # Read and summarise results.json
    results_file = SCRIPT_DIR / "results.json"
    if results_file.exists():
        with open(results_file) as f:
            data = json.load(f)
        tests = data.get("results", [])
        passed = sum(1 for t in tests if t.get("passed"))
        failed = len(tests) - passed
        print(f"\n  Summary: {passed} passed, {failed} failed out of {len(tests)}")
    else:
        print("\n  ⚠ No results.json produced")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
