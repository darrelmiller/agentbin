#!/usr/bin/env python3
"""
AgentBin Acceptance Test Runner & Dashboard Generator

Runs all client test suites (dotnet, go, python, java) against the AgentBin service,
collects results.json from each, and generates a static HTML compatibility dashboard.

Usage:
    python run-all.py [baseUrl]
    python run-all.py --dashboard-only   # skip running, just regenerate HTML from existing results.json files
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
TESTS_DIR = Path(__file__).parent
CLIENTS_DIR = TESTS_DIR / "ClientTests"

BINDINGS = ["jsonrpc", "rest"]

BASE_TESTS = [
    ("agent-card-echo", "Echo Agent Card", "Discovery"),
    ("agent-card-spec", "Spec Agent Card", "Discovery"),
    ("echo-send-message", "Echo Send Message", "Echo Agent"),
    ("spec-message-only", "Message Only", "Spec Agent"),
    ("spec-task-lifecycle", "Task Lifecycle", "Spec Agent"),
    ("spec-get-task", "GetTask", "Spec Agent"),
    ("spec-task-failure", "Task Failure", "Spec Agent"),
    ("spec-data-types", "Data Types", "Spec Agent"),
    ("spec-streaming", "Streaming", "Spec Agent"),
    ("spec-multi-turn", "Multi-Turn", "Spec Agent"),
    ("spec-task-cancel", "Task Cancel (via streaming)", "Spec Agent"),
    ("spec-cancel-with-metadata", "Cancel With Metadata", "Spec Agent"),
    ("spec-list-tasks", "ListTasks", "Spec Agent"),
    ("spec-return-immediately", "Return Immediately", "Spec Agent"),
    ("error-task-not-found", "Task Not Found Error", "Error Handling"),
    # --- TCK-inspired interop tests ---
    ("error-cancel-not-found", "Cancel Not Found", "Error Handling"),
    ("error-cancel-terminal", "Cancel Terminal Task", "Error Handling"),
    ("error-send-terminal", "Send To Terminal Task", "Error Handling"),
    ("error-send-invalid-task", "Send Invalid TaskId", "Error Handling"),
    ("error-push-not-supported", "Push Not Supported", "Error Handling"),
    ("subscribe-to-task", "SubscribeToTask", "Streaming"),
    ("error-subscribe-not-found", "Subscribe Not Found", "Error Handling"),
    ("stream-message-only", "Stream Message Only", "Streaming"),
    ("stream-task-lifecycle", "Stream Task Lifecycle", "Streaming"),
    ("multi-turn-context-preserved", "Context Preserved", "Multi-Turn"),
    ("get-task-with-history", "GetTask With History", "GetTask"),
    ("get-task-after-failure", "GetTask After Failure", "GetTask"),
]

# v0.3 backward-compatibility tests — clients talk to an agent with a v0.3 card
V03_TESTS = [
    ("spec03-agent-card", "v0.3 Agent Card", "v0.3 Discovery"),
    ("spec03-send-message", "v0.3 Send Message", "v0.3 Interop"),
    ("spec03-task-lifecycle", "v0.3 Task Lifecycle", "v0.3 Interop"),
    ("spec03-streaming", "v0.3 Streaming", "v0.3 Interop"),
]

# Full test IDs include binding prefix
STANDARD_TESTS = [
    (f"{binding}/{test_id}", test_name, cat)
    for binding in BINDINGS
    for test_id, test_name, cat in BASE_TESTS
]

# v0.3 tests use "v03" prefix
V03_FULL_TESTS = [
    (f"v03/{test_id}", test_name, cat)
    for test_id, test_name, cat in V03_TESTS
]

ALL_TESTS = STANDARD_TESTS + V03_FULL_TESTS

CLIENTS = {
    "dotnet": {
        "name": ".NET",
        "dir": "dotnet",
        "icon": "&#9726;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/dotnet/Program.cs",
        "sdk_url": "https://www.nuget.org/packages/A2A/",
    },
    "go": {
        "name": "Go",
        "dir": "go",
        "icon": "&#9671;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/go/main.go",
        "sdk_url": "https://pkg.go.dev/github.com/a2aproject/a2a-go/v2",
    },
    "python": {
        "name": "Python",
        "dir": "python",
        "icon": "&#9673;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/python/test_python_client.py",
        "sdk_url": "https://pypi.org/project/a2a-sdk/1.0.0a0/",
    },
    "java": {
        "name": "Java",
        "dir": "java",
        "icon": "&#9672;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/java/src/main/java/agentbin/TestJavaClient.java",
        "sdk_url": "https://github.com/a2aproject/a2a-java",
    },
    "js": {
        "name": "JavaScript",
        "dir": "js",
        "icon": "&#9724;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/js/test_js_client.mjs",
        "sdk_url": "https://github.com/a2aproject/a2a-js",
    },
}


def run_client(client_id: str, base_url: str) -> dict | None:
    """Run a client's standalone run.py script to execute tests and produce results.json."""
    info = CLIENTS[client_id]
    cwd = CLIENTS_DIR / info["dir"]
    run_script = cwd / "run.py"

    # Each client owns its own run.py; fall back to legacy commands if missing
    if run_script.exists():
        cmd = [sys.executable, str(run_script), base_url]
    else:
        print(f"  ⚠ No run.py found for {info['name']} — skipping")
        return None

    print(f"\n{'='*60}")
    print(f"  Running {info['icon']} {info['name']} client tests...")
    print(f"  cwd: {cwd}")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), capture_output=False, timeout=300
        )
        results_file = cwd / "results.json"
        if results_file.exists():
            with open(results_file) as f:
                return json.load(f)
        else:
            print(f"  ⚠ No results.json found for {info['name']}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  ⚠ {info['name']} timed out after 300s")
        return None
    except FileNotFoundError:
        print(f"  ⚠ {info['name']} runtime not found ({cmd[0]})")
        return None
    except Exception as e:
        print(f"  ⚠ {info['name']} error: {e}")
        return None


def load_existing_results() -> dict[str, dict]:
    all_results = {}
    for client_id, info in CLIENTS.items():
        results_file = CLIENTS_DIR / info["dir"] / "results.json"
        if results_file.exists():
            with open(results_file) as f:
                all_results[client_id] = json.load(f)
    return all_results


# Known failure annotations: (client_pattern, test_id_pattern) -> explanation
# client_pattern: exact client id or "*" for all clients
# test_id_pattern: exact test id or a substring match
KNOWN_FAILURES: dict[tuple[str, str], str] = {
    # ── Cross-client: server does not implement returnImmediately ──
    ("*", "spec-return-immediately"):
        "Known: .NET A2A server does not implement returnImmediately. "
        "The SDK blocks until the task completes instead of returning early.",

    # ── .NET SDK — no REST transport, subscribe streaming error ──
    ("dotnet", "rest/"):
        "Known: .NET A2A SDK does not support REST (HTTP+JSON) transport. "
        "Only JSON-RPC binding is available.",
    ("dotnet", "jsonrpc/subscribe-to-task"):
        "Known: SubscribeToTask returns 'internal error during streaming' — "
        "server-side issue with resubscription to completed tasks.",

    # ── Go SDK — REST cancel metadata, subscribe, v0.3 not supported ──
    ("go", "rest/spec-cancel-with-metadata"):
        "Known: REST cancel succeeds but metadata is nil in response. "
        "Server does not echo cancel metadata back via REST binding.",
    ("go", "rest/subscribe-to-task"):
        "Known: REST SubscribeToTask returns server error. "
        "Server-side issue with REST SSE resubscription.",
    ("go", "v03/spec03-send-message"):
        "Known: Go SDK rejects v0.3 agent card — 'no supported interfaces'. "
        "V1.0 SDK does not fall back to v0.3 protocol.",
    ("go", "v03/spec03-task-lifecycle"):
        "Known: Go SDK rejects v0.3 agent card. Same root cause as spec03-send-message.",
    ("go", "v03/spec03-streaming"):
        "Known: Go SDK rejects v0.3 agent card. Same root cause as spec03-send-message.",

    # ── Python SDK — REST subscribe/cancel metadata, v0.3 method names ──
    ("python", "rest/subscribe-to-task"):
        "Known: Python SDK REST subscribe returns 0 events. "
        "Possible server or SDK issue with REST SSE subscription.",
    ("python", "rest/spec-cancel-with-metadata"):
        "Known: Python SDK REST cancel succeeds but metadata keys are empty. "
        "REST binding does not echo cancel metadata back in response.",
    ("python", "v03/spec03-send-message"):
        "Known: Python SDK sends v1.0 method names (message/send) to v0.3 agent "
        "which only accepts v0.3 method names (tasks/send). SDK does not fall back.",
    ("python", "v03/spec03-task-lifecycle"):
        "Known: Python SDK sends v1.0 method names to v0.3 agent. "
        "Same root cause as spec03-send-message.",
    ("python", "v03/spec03-streaming"):
        "Known: Python SDK sends v1.0 method names to v0.3 agent. "
        "Same root cause as spec03-send-message.",

    # ── Java SDK (Beta1-SNAPSHOT) — agent card protobuf deserialization ──
    ("java", "agent-card-echo"):
        "Known: Java SDK uses protobuf internally to parse agent cards. "
        "The .NET server emits null for repeated fields (extensions, inputModes, outputModes) "
        "which protobuf JSON parsing rejects.",
    ("java", "agent-card-spec"):
        "Known: Java SDK uses protobuf internally to parse agent cards. "
        "The .NET server emits null for repeated fields which protobuf JSON parsing rejects.",

    # ── Java SDK (Beta1) — JSONRPC null-ID bug ──
    # Beta1 protobuf conversion produces null message 'id'; server rejects with
    # InvalidParamsError: Parameter 'id' may not be null.
    ("java", "jsonrpc/spec-task-lifecycle"):
        "Known: Java SDK Beta1 protobuf conversion produces null message 'id'. "
        "Server rejects with InvalidParamsError: Parameter 'id' may not be null.",
    ("java", "jsonrpc/spec-get-task"):
        "Known: Skipped because task-lifecycle fails (no task ID to query).",
    ("java", "jsonrpc/spec-task-failure"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-data-types"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-streaming"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-multi-turn"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-task-cancel"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-cancel-with-metadata"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/spec-list-tasks"):
        "Known: Java SDK JSONRPC listTasks returns 0 results — "
        "likely protobuf deserialization issue with task list response.",
    ("java", "jsonrpc/spec-return-immediately"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/error-cancel-terminal"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/error-send-terminal"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/error-send-invalid-task"):
        "Known: Java SDK Beta1 — expected error but got success. "
        "SDK may not send the correct task ID due to protobuf null-ID bug.",
    ("java", "jsonrpc/subscribe-to-task"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/error-subscribe-not-found"):
        "Known: Java SDK Beta1 — expected error but got success. "
        "SDK may not send the correct task ID due to protobuf null-ID bug.",
    ("java", "jsonrpc/stream-task-lifecycle"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/multi-turn-context-preserved"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/get-task-with-history"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",
    ("java", "jsonrpc/get-task-after-failure"):
        "Known: Java SDK Beta1 protobuf null 'id' bug. Same root cause as spec-task-lifecycle.",

    # ── Java SDK (Beta1) — REST-specific failures ──
    # Beta1 fixed the SUBMITTED-state issue for basic REST tests (task-lifecycle,
    # task-failure, data-types, multi-turn now pass). Remaining REST failures:
    ("java", "rest/spec-cancel-with-metadata"):
        "Known: REST cancel succeeds but cancel metadata (reason/requestedBy) "
        "not echoed in response. Server-side limitation.",
    ("java", "rest/spec-list-tasks"):
        "Known: Java SDK REST listTasks fails with InvalidParamsError — "
        "protobuf null 'id' bug affects list request.",
    ("java", "rest/error-send-terminal"):
        "Known: Java SDK Beta1 — expected error but got success. "
        "REST binding may not properly propagate terminal-state errors.",
    ("java", "rest/error-send-invalid-task"):
        "Known: Java SDK Beta1 — expected error but got success. "
        "REST binding may not properly propagate task-not-found errors.",
    ("java", "rest/subscribe-to-task"):
        "Known: Java SDK REST subscribe times out. "
        "Server-side issue with REST SSE subscription.",
    ("java", "rest/error-subscribe-not-found"):
        "Known: Java SDK Beta1 — expected error but got success. "
        "REST binding may not properly propagate subscription errors.",

    # ── Java SDK (Beta1) — v0.3 failures ──
    ("java", "v03/spec03-task-lifecycle"):
        "Known: Java SDK Beta1 protobuf null 'id' bug affects v0.3 tests. "
        "Same root cause as JSONRPC null-ID issue.",
    ("java", "v03/spec03-streaming"):
        "Known: Java SDK Beta1 protobuf null 'id' bug affects v0.3 tests. "
        "Same root cause as JSONRPC null-ID issue.",

    # ── JS SDK (V1.0 with compat layer) ──
    ("js", "jsonrpc/spec-list-tasks"):
        "Known: JS SDK does not expose listTasks method.",
    ("js", "rest/spec-list-tasks"):
        "Known: JS SDK does not expose listTasks method.",
    ("js", "jsonrpc/error-subscribe-not-found"):
        "Known: Server returns 'internal error during streaming' instead of "
        "NotFound error. Server-side issue with subscription error handling.",
    ("js", "jsonrpc/get-task-with-history"):
        "Known: Server returns task with 0 history items. "
        "Server may not persist message history for getTask requests.",
    ("js", "rest/spec-cancel-with-metadata"):
        "Known: REST cancel succeeds but metadata keys are empty. "
        "REST binding does not echo cancel metadata back in response.",
    ("js", "rest/subscribe-to-task"):
        "Known: REST subscribe returns 0 events. "
        "Server-side issue with REST SSE resubscription to completed tasks.",
    ("js", "rest/get-task-with-history"):
        "Known: Server returns task with 0 history items. "
        "Server may not persist message history for getTask requests.",
}


def _get_known_failure(client_id: str, test_id: str) -> str | None:
    """Look up a known failure annotation for a (client, test) pair."""
    # Try exact match first
    if (client_id, test_id) in KNOWN_FAILURES:
        return KNOWN_FAILURES[(client_id, test_id)]
    # Try wildcard client
    if ("*", test_id) in KNOWN_FAILURES:
        return KNOWN_FAILURES[("*", test_id)]
    # Try matching just the base test id (without binding prefix)
    base_id = test_id.split("/")[-1] if "/" in test_id else test_id
    if (client_id, base_id) in KNOWN_FAILURES:
        return KNOWN_FAILURES[(client_id, base_id)]
    if ("*", base_id) in KNOWN_FAILURES:
        return KNOWN_FAILURES[("*", base_id)]
    # Try prefix matching (e.g., "rest/" matches all REST tests)
    for (cid, pattern), explanation in KNOWN_FAILURES.items():
        if cid in (client_id, "*") and pattern.endswith("/") and test_id.startswith(pattern):
            return explanation
    return None


def generate_dashboard(all_results: dict[str, dict], base_url: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build lookup: client -> test_id -> result
    matrix: dict[str, dict[str, dict]] = {}
    for client_id, data in all_results.items():
        matrix[client_id] = {}
        for r in data.get("results", []):
            rid = r.get("id") or r.get("Id")
            matrix[client_id][rid] = r

    # Order clients by the CLIENTS dict order
    ordered_clients = [c for c in CLIENTS if c in all_results]

    # Compute totals per client
    totals = {}
    for cid in ordered_clients:
        results_list = all_results[cid].get("results", [])
        p = sum(1 for r in results_list if r.get("passed") or r.get("Passed"))
        f = len(results_list) - p
        totals[cid] = (p, f)

    # Build table rows grouped by binding then category
    rows_html = ""

    def _render_cell(cid, full_id):
        """Render a single result cell for a client/test pair."""
        r = matrix.get(cid, {}).get(full_id)
        if r is None:
            return '<td class="skip" title="Not implemented">&mdash;</td>'
        elif r.get("passed") or r.get("Passed"):
            detail = r.get("detail", r.get("Detail", ""))
            dur = r.get("durationMs") or r.get("DurationMs") or ""
            tip = f"{detail}\n({dur}ms)" if dur else detail
            return f'<td class="pass" title="{_esc(tip)}">&#10004;</td>'
        else:
            detail = r.get("detail", r.get("Detail", ""))
            known = _get_known_failure(cid, full_id)
            if known:
                tip = f"{detail}\n\n⚠ {known}"
                return f'<td class="fail known" title="{_esc(tip)}">&#10008;</td>'
            else:
                return f'<td class="fail" title="{_esc(detail)}">&#10008;</td>'

    for binding in BINDINGS:
        binding_label = "JSON-RPC" if binding == "jsonrpc" else "HTTP+JSON (REST)"
        rows_html += f'<tr class="binding-row"><td colspan="{1 + len(ordered_clients)}">{binding_label}</td></tr>\n'

        # Group base tests by category
        categories: dict[str, list[tuple[str, str]]] = {}
        for test_id, test_name, cat in BASE_TESTS:
            categories.setdefault(cat, []).append((test_id, test_name))

        for cat, tests in categories.items():
            rows_html += f'<tr class="cat-row"><td colspan="{1 + len(ordered_clients)}">{cat}</td></tr>\n'
            for test_id, test_name in tests:
                full_id = f"{binding}/{test_id}"
                cells = f'<td class="test-name" title="{full_id}"><a href="tests.html#{test_id}" target="_parent" style="color:inherit;text-decoration:none;border-bottom:1px dotted var(--muted,#8b949e)">{test_name}</a></td>'
                for cid in ordered_clients:
                    cells += _render_cell(cid, full_id)
                rows_html += f"<tr>{cells}</tr>\n"

    # v0.3 backward-compatibility section
    if V03_TESTS:
        rows_html += f'<tr class="binding-row"><td colspan="{1 + len(ordered_clients)}">v0.3 Backward Compatibility</td></tr>\n'
        v03_categories: dict[str, list[tuple[str, str]]] = {}
        for test_id, test_name, cat in V03_TESTS:
            v03_categories.setdefault(cat, []).append((test_id, test_name))
        for cat, tests in v03_categories.items():
            rows_html += f'<tr class="cat-row"><td colspan="{1 + len(ordered_clients)}">{cat}</td></tr>\n'
            for test_id, test_name in tests:
                full_id = f"v03/{test_id}"
                cells = f'<td class="test-name" title="{full_id}"><a href="tests.html#{test_id}" target="_parent" style="color:inherit;text-decoration:none;border-bottom:1px dotted var(--muted,#8b949e)">{test_name}</a></td>'
                for cid in ordered_clients:
                    cells += _render_cell(cid, full_id)
                rows_html += f"<tr>{cells}</tr>\n"

    # Header columns
    header_cells = "<th>Test</th>"
    for cid in ordered_clients:
        info = CLIENTS[cid]
        sdk = all_results[cid].get("sdk", "")
        p, f = totals[cid]
        color = "#3fb950" if f == 0 else "#f85149"
        source_link = info.get("source", "")
        sdk_url = info.get("sdk_url", "")
        sdk_html = f'<a href="{sdk_url}" target="_blank" style="color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--muted)">{sdk}</a>' if sdk_url and sdk else f'<small>{sdk}</small>'
        src_html = f'<a href="{source_link}" target="_blank" style="color:#58a6ff;text-decoration:none;font-size:0.7rem">source</a>' if source_link else ""
        header_cells += (
            f'<th>{info["name"]}<br>'
            f'<small>{sdk_html}</small><br>'
            f'<span style="color:{color};font-weight:bold">{p}/{p+f}</span>'
            f'{" &middot; " + src_html if src_html else ""}</th>'
        )

    # Summary bar
    total_pass = sum(t[0] for t in totals.values())
    total_fail = sum(t[1] for t in totals.values())
    total_all = total_pass + total_fail
    pct = (total_pass / total_all * 100) if total_all else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentBin A2A Compatibility Dashboard</title>
<style>
  :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3; --muted: #8b949e; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); padding: 1.5rem; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 1rem; font-size: 0.8rem; }}
  .summary {{ display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }}
  .summary-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
                   padding: 0.6rem 1rem; min-width: 100px; }}
  .summary-card .label {{ color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  .summary-card .value {{ font-size: 1.4rem; font-weight: 700; }}
  .bar {{ height: 4px; border-radius: 2px; background: #f85149; margin-top: 0.3rem; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: #3fb950; border-radius: 2px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 6px;
           overflow: hidden; border: 1px solid var(--border); font-size: 0.8rem; }}
  th {{ background: #21262d; padding: 6px 10px; text-align: center; font-size: 0.78rem;
       border-bottom: 2px solid var(--border); vertical-align: top; white-space: nowrap; }}
  th:first-child {{ text-align: left; }}
  td {{ padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: center;
       font-size: 0.95rem; vertical-align: middle; line-height: 1.3; }}
  .test-name {{ text-align: left; font-size: 0.78rem; white-space: nowrap; }}
  .binding-row td {{ background: #1c2128; font-weight: 700; font-size: 0.75rem; text-transform: uppercase;
                     color: var(--text); letter-spacing: 0.06em; padding: 5px 10px;
                     border-top: 2px solid var(--border); }}
  .cat-row td {{ background: #21262d; font-weight: 600; font-size: 0.72rem; text-transform: uppercase;
                 color: var(--muted); letter-spacing: 0.04em; padding: 3px 10px; }}
  .pass {{ color: #3fb950; cursor: help; font-weight: bold; }}
  .fail {{ color: #f85149; cursor: help; font-weight: bold; }}
  .fail.known {{ color: #d29922; }}
  .skip {{ color: var(--muted); font-size: 0.75rem; }}
  tr:hover td:not(.cat-row td):not(.binding-row td) {{ background: rgba(255,255,255,0.03); }}
  .footer {{ color: var(--muted); font-size: 0.7rem; margin-top: 0.8rem; }}
  small {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>AgentBin A2A Compatibility Dashboard</h1>
<p class="subtitle">Generated {timestamp} &bull; Target: <code>{base_url}</code></p>

<div class="summary">
  <div class="summary-card">
    <div class="label">Tests</div>
    <div class="value">{total_all}</div>
  </div>
  <div class="summary-card">
    <div class="label">Passing</div>
    <div class="value" style="color:#3fb950">{total_pass}</div>
    <div class="bar"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>
  </div>
  <div class="summary-card">
    <div class="label">Failing</div>
    <div class="value" style="color:{'#f85149' if total_fail else '#3fb950'}">{total_fail}</div>
  </div>
  <div class="summary-card">
    <div class="label">Clients</div>
    <div class="value">{len(ordered_clients)}</div>
  </div>
</div>

<table>
<thead><tr>{header_cells}</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>

<p class="footer">
  Hover over cells for details &bull;
  Clients: {', '.join(f'{CLIENTS[c]["name"]}' for c in ordered_clients)}
</p>
</body>
</html>"""
    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "&#10;")


def main():
    base_url = BASE_URL
    dashboard_only = False

    for arg in sys.argv[1:]:
        if arg == "--dashboard-only":
            dashboard_only = True
        elif not arg.startswith("-"):
            base_url = arg.rstrip("/")

    if dashboard_only:
        print("Dashboard-only mode — loading existing results.json files")
        all_results = load_existing_results()
    else:
        all_results = {}
        for client_id in CLIENTS:
            data = run_client(client_id, base_url)
            if data:
                all_results[client_id] = data

    if not all_results:
        print("No results collected. Exiting.")
        return 1

    html = generate_dashboard(all_results, base_url)
    out_path = TESTS_DIR / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"\n✅ Dashboard written to {out_path}")

    # Also copy to docs/ for GitHub Pages
    docs_path = TESTS_DIR.parent / "docs" / "dashboard.html"
    if docs_path.parent.exists():
        docs_path.write_text(html, encoding="utf-8")
        print(f"✅ Dashboard copied to {docs_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
