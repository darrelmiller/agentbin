#!/usr/bin/env python3
"""
Standalone Go A2A SDK Test Runner

Builds the Go test client with `go build`, runs the compiled binary against a
configurable base URL, and produces results.json + a summary on stdout.

Usage:
    python run.py [base_url]

Default base URL:
    https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io
"""

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = (
    "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
)

SCRIPT_DIR = Path(__file__).resolve().parent
BINARY_NAME = "test_go_client.exe" if sys.platform == "win32" else "test_go_client"


def build(cwd: Path) -> Path:
    """Compile the Go test client and return the path to the binary."""
    binary = cwd / BINARY_NAME
    print(f"  Building Go client → {BINARY_NAME}")
    result = subprocess.run(
        ["go", "build", "-o", BINARY_NAME, "."],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print("  ✗ Build failed:")
        print(result.stderr)
        sys.exit(1)
    print("  ✓ Build succeeded")
    return binary


def run_tests(binary: Path, base_url: str, cwd: Path) -> dict | None:
    """Execute the compiled binary and return parsed results.json."""
    print(f"  Running tests against {base_url}")
    result = subprocess.run(
        [str(binary), base_url],
        cwd=str(cwd),
        capture_output=False,
        timeout=300,
    )
    results_file = cwd / "results.json"
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            return json.load(f)
    print("  ⚠ No results.json produced")
    return None


def print_summary(report: dict) -> None:
    """Print a human-readable summary of the test results."""
    results = report.get("results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed

    print(f"\n{'='*50}")
    print(f"  Go A2A SDK Test Results")
    print(f"  SDK:  {report.get('sdk', 'unknown')}")
    print(f"  Base: {report.get('baseUrl', 'unknown')}")
    print(f"{'='*50}")
    print(f"  ✓ {passed} passed, ✗ {failed} failed  (out of {total})")

    if failed > 0:
        print(f"\n  Failed tests:")
        for r in results:
            if not r.get("passed"):
                detail = r.get("detail", "")
                short = (detail[:80] + "…") if len(detail) > 80 else detail
                print(f"    ✗ {r['id']}: {short}")

    print(f"{'='*50}\n")


def main():
    # Ensure UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    cwd = SCRIPT_DIR

    print(f"\n{'='*50}")
    print(f"  Go A2A SDK — Standalone Test Runner")
    print(f"{'='*50}\n")

    binary = build(cwd)
    report = run_tests(binary, base_url, cwd)

    if report is None:
        print("  ✗ No results produced — tests may have crashed.")
        sys.exit(1)

    print_summary(report)

    # Exit with non-zero if any test failed
    failed = sum(1 for r in report.get("results", []) if not r.get("passed"))
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
