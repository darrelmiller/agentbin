#!/usr/bin/env python3
"""Standalone Swift A2A SDK Test Runner"""
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
SCRIPT_DIR = Path(__file__).resolve().parent


def get_swift_env():
    """Get environment with Swift + MSVC on Windows, or passthrough on Unix."""
    if sys.platform != "win32":
        return os.environ.copy()

    # Find Swift
    swift_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Swift"
    toolchains = sorted(swift_base.glob("Toolchains/*/usr/bin/swift.exe"), reverse=True)
    runtimes = sorted(swift_base.glob("Runtimes/*/usr/bin"), reverse=True)
    sdks = sorted(swift_base.glob("Platforms/*/Windows.platform/Developer/SDKs/Windows.sdk"), reverse=True)
    if not toolchains:
        print("  ✗ Swift toolchain not found")
        sys.exit(1)
    swift_bin = str(toolchains[0].parent)
    runtime_bin = str(runtimes[0]) if runtimes else ""
    sdkroot = str(sdks[0]) if sdks else ""

    # Find vcvarsall.bat via vswhere
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        print("  ✗ Visual Studio not found (vswhere missing)")
        sys.exit(1)
    vs_path = subprocess.check_output(
        [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
        text=True
    ).strip()
    vcvarsall = Path(vs_path) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"

    # Capture MSVC environment
    result = subprocess.run(
        f'"{vcvarsall}" x64 >nul 2>&1 && set',
        shell=True, capture_output=True, text=True
    )
    env = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env[k] = v

    # Prepend Swift paths
    env["PATH"] = f"{swift_bin};{runtime_bin};{env.get('PATH', '')}"
    if sdkroot:
        env["SDKROOT"] = sdkroot
    return env


def patch_foundation_networking(cwd):
    """Patch checked-out a2a-client-swift sources to import FoundationNetworking on non-Apple."""
    if sys.platform == "darwin":
        return
    checkout = cwd / ".build" / "checkouts" / "a2a-client-swift" / "Sources"
    if not checkout.exists():
        return
    patch_marker = "#if canImport(FoundationNetworking)"
    for swift_file in checkout.rglob("*.swift"):
        content = swift_file.read_text(encoding="utf-8")
        if "import Foundation" in content and "FoundationNetworking" not in content:
            swift_file.chmod(0o644)
            content = content.replace(
                "import Foundation",
                "import Foundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif"
            )
            # Replace URLSession.shared.bytes(for:) with data(for:) fallback
            if "URLSession.shared.bytes(for:" in content:
                # This is a known Apple-only API; needs platform-specific handling
                pass
            swift_file.write_text(content, encoding="utf-8")
            print(f"    patched: {swift_file.name}")


def build(cwd, env):
    print("  Building Swift client...")
    # First resolve dependencies (creates .build/checkouts)
    subprocess.run(
        ["swift", "package", "resolve"],
        cwd=str(cwd), capture_output=True, text=True, env=env, timeout=120
    )
    # Patch upstream SDK for non-Apple platforms
    patch_foundation_networking(cwd)
    result = subprocess.run(
        ["swift", "build", "-c", "release"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if result.returncode != 0:
        print("  ✗ Build failed:")
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
        sys.exit(1)
    print("  ✓ Build succeeded")


def find_binary(cwd):
    """Find the built binary in .build/release/"""
    binary = cwd / ".build" / "release" / "TestSwiftClient"
    if sys.platform == "win32":
        binary = binary.with_suffix(".exe")
    return binary


def run_tests(binary, base_url, cwd, env):
    print(f"  Running tests against {base_url}")
    subprocess.run(
        [str(binary), base_url],
        cwd=str(cwd),
        capture_output=False,
        timeout=300,
        env=env,
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

    env = get_swift_env()
    build(SCRIPT_DIR, env)
    binary = find_binary(SCRIPT_DIR)

    if not binary.exists():
        print(f"  ✗ Binary not found at {binary}")
        sys.exit(1)

    report = run_tests(binary, base_url, SCRIPT_DIR, env)
    if report:
        print_summary(report)
    else:
        print("  ✗ No results produced")
        sys.exit(1)


if __name__ == "__main__":
    main()
