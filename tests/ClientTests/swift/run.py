#!/usr/bin/env python3
"""Standalone Swift A2A SDK Test Runner"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
SCRIPT_DIR = Path(__file__).resolve().parent


def get_swift_env():
    """Get environment with Swift + MSVC on Windows, or passthrough on Unix.
    
    Returns (env_dict, swift_exe_path) — use swift_exe_path for subprocess calls
    because Python on Windows doesn't search custom env PATH for executables.
    """
    if sys.platform != "win32":
        swift_exe = shutil.which("swift") or "swift"
        return os.environ.copy(), swift_exe

    # Find Swift
    swift_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Swift"
    toolchains = sorted(swift_base.glob("Toolchains/*/usr/bin/swift.exe"), reverse=True)
    runtimes = sorted(swift_base.glob("Runtimes/*/usr/bin"), reverse=True)
    sdks = sorted(swift_base.glob("Platforms/*/Windows.platform/Developer/SDKs/Windows.sdk"), reverse=True)
    if not toolchains:
        print("  ✗ Swift toolchain not found")
        sys.exit(1)
    swift_exe = str(toolchains[0])
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

    # Prepend Swift paths — vcvarsall uses "Path" (mixed case) on Windows
    path_key = next((k for k in env if k.lower() == "path"), "PATH")
    env[path_key] = f"{swift_bin};{runtime_bin};{env.get(path_key, '')}"
    if sdkroot:
        env["SDKROOT"] = sdkroot
    return env, swift_exe


def patch_upstream_sdk(cwd):
    """Patch checked-out a2a-client-swift sources for compatibility.
    
    Patches applied:
    1. Import FoundationNetworking (non-Apple only, needed for URLSession)
    2. Replace URLSession.shared.bytes(for:) with data(for:) fallback (non-Apple only)
    3. Fix JSON-RPC method names: SDK sends v0.3 slash-format (message/send)
       but A2A v1.0 spec uses PascalCase (SendMessage)
    4. Fix MessageRole enum values: SDK sends "user"/"agent" (v0.3) but server
       expects "ROLE_USER"/"ROLE_AGENT" (v1.0 proto enum names)
    5. Remove v0.3 "kind" discriminator from Part and Message encoding
    """
    checkout = cwd / ".build" / "checkouts" / "a2a-client-swift" / "Sources"
    if not checkout.exists():
        return

    # Method name mapping: SDK v0.3 → server v1.0
    method_replacements = {
        '"message/send"': '"SendMessage"',
        '"message/stream"': '"SendStreamingMessage"',
        '"tasks/get"': '"GetTask"',
        '"tasks/list"': '"ListTasks"',
        '"tasks/cancel"': '"CancelTask"',
        '"tasks/resubscribe"': '"SubscribeToTask"',
        '"tasks/pushNotificationConfig/set"': '"CreateTaskPushNotificationConfig"',
        '"tasks/pushNotificationConfig/get"': '"GetTaskPushNotificationConfig"',
        '"tasks/pushNotificationConfig/list"': '"ListTaskPushNotificationConfig"',
        '"tasks/pushNotificationConfig/delete"': '"DeleteTaskPushNotificationConfig"',
        '"agent/authenticatedExtendedCard"': '"GetAuthenticatedExtendedCard"',
    }

    is_non_apple = sys.platform != "darwin"

    for swift_file in checkout.rglob("*.swift"):
        content = swift_file.read_text(encoding="utf-8")
        changed = False

        # Patch 1: Add FoundationNetworking import (non-Apple only)
        if is_non_apple and "import Foundation" in content and "FoundationNetworking" not in content:
            content = content.replace(
                "import Foundation",
                "import Foundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif"
            )
            changed = True

        # Patch 2: Replace Apple-only bytes(for:) streaming with data(for:) fallback
        if is_non_apple and "URLSession.shared.bytes(for:" in content:
            content = content.replace(
                "let (bytes, response) = try await URLSession.shared.bytes(for: urlRequest)",
                "let (data, response) = try await URLSession.shared.data(for: urlRequest)"
            )
            content = content.replace(
                "for try await line in bytes.lines {",
                "let responseText = String(data: data, encoding: .utf8) ?? \"\"\n                    for line in responseText.components(separatedBy: \"\\n\") {"
            )
            changed = True

        # Patch 3: Fix JSON-RPC method names to v1.0 PascalCase
        for old, new in method_replacements.items():
            if old in content:
                content = content.replace(old, new)
                changed = True

        # Patch 4: Fix MessageRole enum values to v1.0 proto format
        if 'case user = "user"' in content:
            content = content.replace('case user = "user"', 'case user = "ROLE_USER"')
            content = content.replace('case agent = "agent"', 'case agent = "ROLE_AGENT"')
            content = content.replace('case unspecified = "unspecified"', 'case unspecified = "ROLE_UNSPECIFIED"')
            changed = True

        # Patch 4b: Fix TaskState enum values to v1.0 proto format
        if 'case completed = "completed"' in content:
            state_map = {
                'case unspecified = "unspecified"': 'case unspecified = "TASK_STATE_UNSPECIFIED"',
                'case submitted = "submitted"': 'case submitted = "TASK_STATE_SUBMITTED"',
                'case working = "working"': 'case working = "TASK_STATE_WORKING"',
                'case completed = "completed"': 'case completed = "TASK_STATE_COMPLETED"',
                'case failed = "failed"': 'case failed = "TASK_STATE_FAILED"',
                'case cancelled = "cancelled"': 'case cancelled = "TASK_STATE_CANCELED"',
                'case inputRequired = "input_required"': 'case inputRequired = "TASK_STATE_INPUT_REQUIRED"',
                'case rejected = "rejected"': 'case rejected = "TASK_STATE_REJECTED"',
                'case authRequired = "auth_required"': 'case authRequired = "TASK_STATE_AUTH_REQUIRED"',
            }
            for old, new in state_map.items():
                content = content.replace(old, new)
            changed = True

        # Patch 5: Remove v0.3 "kind" discriminator from encoding
        # Remove kind encoding from Part.encode(to:)
        if 'try container.encode("text", forKey: .kind)' in content:
            # Remove the entire kind encoding block from Part
            for kind_val in ['"text"', '"file"', '"data"', '"message"']:
                content = content.replace(
                    f'try container.encode({kind_val}, forKey: .kind)\n', ''
                )
            # Also remove the if/else if blocks that gate kind encoding
            import re
            # Remove: if text != nil { ... } else if raw != nil { ... } etc
            content = re.sub(
                r'\s+// Encode kind discriminator\n'
                r'\s+if text != nil \{\n'
                r'\s+\} else if raw != nil \{\n'
                r'\s+\} else if url != nil \{\n'
                r'\s+\} else if data != nil \{\n'
                r'\s+\}',
                '', content
            )
            changed = True

        # Remove kind encoding from Message.encode(to:)
        if 'try container.encode("message", forKey: .kind)' in content:
            content = content.replace(
                '        try container.encode("message", forKey: .kind)\n', ''
            )
            changed = True

        # Patch 6: Fix streaming event decoder to handle v1.0 keyed format
        # The SDK uses kind-based discrimination (v0.3) but server sends
        # keyed wrapper format: {"task": {...}}, {"statusUpdate": {...}}, etc.
        # Add StreamResponse-based fallback before the error throw.
        old_streaming = (
            '        // Fallback: try direct kind-based decoding (without JSON-RPC wrapper)\n'
            '        if let result = try? decoder.decode(StreamEventResult.self, from: data) {\n'
            '            return result.event\n'
            '        }\n'
            '\n'
            '        throw A2AError.invalidResponse(message: "Unknown streaming event format")'
        )
        new_streaming = (
            '        // Try v1.0 keyed format: {"task":..}, {"statusUpdate":..}, etc.\n'
            '        if let rpcWrapped = try? decoder.decode(JSONRPCResponse<StreamResponse>.self, from: data) {\n'
            '            if let error = rpcWrapped.error { throw error.toA2AError() }\n'
            '            if let result = rpcWrapped.result { return StreamingEvent(from: result) }\n'
            '        }\n'
            '        if let direct = try? decoder.decode(StreamResponse.self, from: data) {\n'
            '            return StreamingEvent(from: direct)\n'
            '        }\n'
            '\n'
            '        // Fallback: try direct kind-based decoding (v0.3 format)\n'
            '        if let result = try? decoder.decode(StreamEventResult.self, from: data) {\n'
            '            return result.event\n'
            '        }\n'
            '\n'
            '        throw A2AError.invalidResponse(message: "Unknown streaming event format")'
        )
        if old_streaming in content:
            content = content.replace(old_streaming, new_streaming)
            changed = True

        # Patch 7: Fix getTask to include task ID in JSON-RPC params
        # SDK puts task ID in URL path (REST) but doesn't include it in
        # query items, so JSON-RPC transport misses it in params.
        old_get_task = (
            '    public func getTask(_ taskId: String, historyLength: Int? = nil) async throws -> A2ATask {\n'
            '        var queryItems: [URLQueryItem] = []\n'
            '        if let historyLength = historyLength {'
        )
        new_get_task = (
            '    public func getTask(_ taskId: String, historyLength: Int? = nil) async throws -> A2ATask {\n'
            '        var queryItems: [URLQueryItem] = [URLQueryItem(name: "id", value: taskId)]\n'
            '        if let historyLength = historyLength {'
        )
        if old_get_task in content:
            content = content.replace(old_get_task, new_get_task)
            changed = True

        # Patch 8: Handle array-format agent card from root well-known endpoint
        # Root /.well-known/agent-card.json returns [AgentCard, ...] (array) but
        # fetchAgentCard expects a single AgentCard object.
        old_fetch = (
            '            let decoder = JSONDecoder()\n'
            '            decoder.dateDecodingStrategy = .iso8601\n'
            '            return try decoder.decode(AgentCard.self, from: data)'
        )
        new_fetch = (
            '            let decoder = JSONDecoder()\n'
            '            decoder.dateDecodingStrategy = .iso8601\n'
            '            if let first = try? decoder.decode([AgentCard].self, from: data).first {\n'
            '                return first\n'
            '            }\n'
            '            return try decoder.decode(AgentCard.self, from: data)'
        )
        if old_fetch in content:
            content = content.replace(old_fetch, new_fetch)
            changed = True

        if changed:
            swift_file.chmod(0o644)
            swift_file.write_text(content, encoding="utf-8")
            print(f"    patched: {swift_file.name}")


def build(cwd, env, swift_exe):
    print("  Building Swift client...")
    # First resolve dependencies (creates .build/checkouts)
    subprocess.run(
        [swift_exe, "package", "resolve"],
        cwd=str(cwd), capture_output=True, text=True, env=env, timeout=120
    )
    # Patch upstream SDK for platform compat and method name alignment
    patch_upstream_sdk(cwd)
    result = subprocess.run(
        [swift_exe, "build", "-c", "release"],
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

    env, swift_exe = get_swift_env()
    build(SCRIPT_DIR, env, swift_exe)
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
