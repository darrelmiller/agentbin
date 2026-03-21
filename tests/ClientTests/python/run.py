#!/usr/bin/env python3
"""
Standalone runner for the A2A Python SDK integration tests.

Usage:
    python run.py [base_url]

Default base URL:
    https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io

The script ensures dependencies are installed, runs the test suite,
produces results.json in the same directory, and prints a summary.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_SCRIPT = HERE / "test_python_client.py"
REQUIREMENTS = HERE / "requirements.txt"
RESULTS_FILE = HERE / "results.json"
DEFAULT_BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"


def _ensure_deps() -> None:
    """Install requirements.txt if any dependency is missing."""
    if not REQUIREMENTS.exists():
        return
    try:
        # Quick smoke-test: can we import the SDK?
        subprocess.check_call(
            [sys.executable, "-c", "import a2a.client; import httpx"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print("[run.py] Installing dependencies from requirements.txt …")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)],
        )


def _print_summary() -> None:
    """Read results.json and print a human-friendly summary."""
    if not RESULTS_FILE.exists():
        print("[run.py] ERROR: results.json was not produced.")
        return

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed

    print()
    print("=" * 64)
    print(f"  SUMMARY: {passed} passed, {failed} failed out of {total}")
    print(f"  SDK:     {data.get('sdk', 'unknown')}")
    print(f"  Target:  {data.get('baseUrl', 'unknown')}")
    print(f"  Results: {RESULTS_FILE}")
    print("=" * 64)
    print()


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE

    _ensure_deps()

    print(f"[run.py] Running tests against {base_url}")
    print()

    rc = subprocess.call(
        [sys.executable, str(TEST_SCRIPT), base_url],
        cwd=str(HERE),
    )

    _print_summary()
    return rc


if __name__ == "__main__":
    sys.exit(main())
