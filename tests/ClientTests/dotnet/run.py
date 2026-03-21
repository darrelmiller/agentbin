#!/usr/bin/env python3
"""
Standalone .NET A2A SDK test runner.

Builds the .NET test client, runs the compiled exe directly (NOT dotnet run),
and produces results.json + a summary line.

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


def find_exe(project_dir: Path) -> Path:
    """Locate the compiled exe under bin/."""
    # Look for the exe built by dotnet build (Debug config, net10.0 TFM)
    patterns = [
        project_dir / "bin" / "Debug" / "net10.0" / "A2AClientTests.exe",
        project_dir / "bin" / "Debug" / "net10.0" / "A2AClientTests",
        project_dir / "bin" / "Release" / "net10.0" / "A2AClientTests.exe",
        project_dir / "bin" / "Release" / "net10.0" / "A2AClientTests",
    ]
    for p in patterns:
        if p.exists():
            return p

    # Fallback: glob for any exe matching the project name
    for exe in sorted(project_dir.rglob("A2AClientTests*")):
        if exe.suffix in (".exe", "") and exe.is_file() and "obj" not in str(exe):
            return exe

    raise FileNotFoundError(
        "Could not find compiled A2AClientTests exe. Did dotnet build succeed?"
    )


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL

    # Ensure UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # --- Step 1: Build ---
    print(f"Building .NET test client...")
    build_result = subprocess.run(
        ["dotnet", "build", "--nologo", "-v", "quiet"],
        cwd=str(SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    if build_result.returncode != 0:
        print("BUILD FAILED:")
        print(build_result.stdout)
        print(build_result.stderr)
        return 2

    print("Build succeeded.\n")

    # --- Step 2: Find and run compiled exe ---
    exe_path = find_exe(SCRIPT_DIR)
    print(f"Running: {exe_path.name} {base_url}\n")

    run_result = subprocess.run(
        [str(exe_path), base_url],
        cwd=str(SCRIPT_DIR),
        timeout=300,
    )

    # --- Step 3: Parse results and print summary ---
    results_file = SCRIPT_DIR / "results.json"
    if not results_file.exists():
        print("\n⚠ results.json not found — test run may have crashed.")
        return 1

    with open(results_file, encoding="utf-8") as f:
        data = json.load(f)

    tests = data.get("results", [])
    passed = sum(1 for t in tests if t.get("Passed") or t.get("passed"))
    failed = len(tests) - passed

    print(f"\n{'='*50}")
    print(f"  .NET SDK: {data.get('sdk', 'unknown')}")
    print(f"  {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*50}")

    if failed > 0:
        print("\nFailed tests:")
        for t in tests:
            is_passed = t.get("Passed") or t.get("passed")
            if not is_passed:
                tid = t.get("Id") or t.get("id", "?")
                detail = t.get("detail") or t.get("Detail", "")
                print(f"  ✗ {tid} — {detail}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
