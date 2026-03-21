#!/usr/bin/env python3
"""
Standalone Java A2A SDK Test Runner

Builds and runs the Java test client via Maven against a configurable base URL,
and produces results.json + a summary on stdout.

Usage:
    python run.py [base_url]

Default base URL:
    https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io
"""

import json
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = (
    "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
)

SCRIPT_DIR = Path(__file__).resolve().parent


def build(cwd: Path) -> None:
    """Compile the Java test client with Maven."""
    print("  Building Java client with Maven...")
    use_shell = sys.platform == "win32"
    result = subprocess.run(
        ["mvn", "-q", "compile"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        shell=use_shell,
    )
    if result.returncode != 0:
        print("  ✗ Build failed:")
        print(result.stderr)
        sys.exit(1)
    print("  ✓ Build succeeded")


def run_tests(base_url: str, cwd: Path) -> dict | None:
    """Execute the Java test client via Maven exec plugin."""
    print(f"  Running tests against {base_url}")
    use_shell = sys.platform == "win32"
    result = subprocess.run(
        ["mvn", "-q", "exec:java", f"-Dexec.args={base_url}"],
        cwd=str(cwd),
        capture_output=False,
        timeout=300,
        shell=use_shell,
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
    print(f"  Java A2A SDK Test Results")
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

    print(f"\n{'='*50}")
    print(f"  Java A2A SDK — Standalone Test Runner")
    print(f"{'='*50}\n")

    build(SCRIPT_DIR)
    report = run_tests(base_url, SCRIPT_DIR)

    if report is None:
        print("  ✗ No results produced — tests may have crashed.")
        sys.exit(1)

    print_summary(report)

    # Exit with non-zero if any test failed
    failed = sum(1 for r in report.get("results", []) if not r.get("passed"))
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
