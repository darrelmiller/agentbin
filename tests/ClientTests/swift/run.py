#!/usr/bin/env python3
"""Standalone Swift A2A SDK Test Runner"""
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
SCRIPT_DIR = Path(__file__).resolve().parent


def build(cwd):
    print("  Building Swift client...")
    result = subprocess.run(
        ["swift", "build", "-c", "release"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print("  ✗ Build failed:")
        print(result.stderr)
        sys.exit(1)
    print("  ✓ Build succeeded")


def find_binary(cwd):
    """Find the built binary in .build/release/"""
    binary = cwd / ".build" / "release" / "TestSwiftClient"
    if sys.platform == "win32":
        binary = binary.with_suffix(".exe")
    return binary


def run_tests(binary, base_url, cwd):
    print(f"  Running tests against {base_url}")
    subprocess.run(
        [str(binary), base_url],
        cwd=str(cwd),
        capture_output=False,
        timeout=300,
    )
    results_file = cwd / "results.json"
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            return json.load(f)
    return None


def print_summary(report):
    results = report.get("results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n{'='*50}")
    print(f"  Swift A2A SDK Test Results")
    print(f"  SDK: {report.get('sdk', 'unknown')}")
    print(f"{'='*50}")
    print(f"  ✓ {passed} passed, ✗ {total - passed} failed (out of {total})")
    print(f"{'='*50}\n")


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL

    build(SCRIPT_DIR)
    binary = find_binary(SCRIPT_DIR)

    if not binary.exists():
        print(f"  ✗ Binary not found at {binary}")
        sys.exit(1)

    report = run_tests(binary, base_url, SCRIPT_DIR)
    if report:
        print_summary(report)
    else:
        print("  ✗ No results produced")
        sys.exit(1)


if __name__ == "__main__":
    main()
