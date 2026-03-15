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
    ("spec-list-tasks", "ListTasks", "Spec Agent"),
    ("spec-return-immediately", "Return Immediately", "Spec Agent"),
    ("error-task-not-found", "Task Not Found Error", "Error Handling"),
]

# Full test IDs include binding prefix
STANDARD_TESTS = [
    (f"{binding}/{test_id}", test_name, cat)
    for binding in BINDINGS
    for test_id, test_name, cat in BASE_TESTS
]

CLIENTS = {
    "dotnet": {
        "name": ".NET",
        "dir": "dotnet",
        "cmd": ["dotnet", "run", "--"],
        "icon": "&#9726;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/dotnet/Program.cs",
    },
    "go": {
        "name": "Go",
        "dir": "go",
        "cmd": ["go", "run", "."],
        "icon": "&#9671;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/go/main.go",
    },
    "python": {
        "name": "Python",
        "dir": "python",
        "cmd": [sys.executable, "test_python_client.py"],
        "icon": "&#9673;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/python/test_python_client.py",
    },
    "java": {
        "name": "Java",
        "dir": "java",
        "cmd_fn": lambda url: ["mvn", "-q", "compile", "exec:java", f"-Dexec.args={url}"],
        "icon": "&#9672;",
        "source": "https://github.com/darrelmiller/agentbin/blob/main/tests/ClientTests/java/src/main/java/agentbin/TestJavaClient.java",
    },
}


def run_client(client_id: str, base_url: str) -> dict | None:
    info = CLIENTS[client_id]
    cwd = CLIENTS_DIR / info["dir"]
    if "cmd_fn" in info:
        cmd = info["cmd_fn"](base_url)
    else:
        cmd = info["cmd"] + [base_url]
    print(f"\n{'='*60}")
    print(f"  Running {info['icon']} {info['name']} client tests...")
    print(f"  cwd: {cwd}")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    try:
        # shell=True needed on Windows for .cmd/.bat wrappers (e.g. mvn.cmd)
        use_shell = sys.platform == "win32"
        result = subprocess.run(
            cmd, cwd=str(cwd), capture_output=False, timeout=300, shell=use_shell
        )
        results_file = cwd / "results.json"
        if results_file.exists():
            with open(results_file) as f:
                return json.load(f)
        else:
            print(f"  ⚠ No results.json found for {info['name']}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  ⚠ {info['name']} timed out after 120s")
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
                cells = f'<td class="test-name" title="{full_id}">{test_name}</td>'
                for cid in ordered_clients:
                    r = matrix.get(cid, {}).get(full_id)
                    if r is None:
                        cells += '<td class="skip" title="Not implemented">&mdash;</td>'
                    elif r.get("passed") or r.get("Passed"):
                        detail = r.get("detail", r.get("Detail", ""))
                        dur = r.get("durationMs") or r.get("DurationMs") or ""
                        tip = f"{detail}\n({dur}ms)" if dur else detail
                        cells += f'<td class="pass" title="{_esc(tip)}">&#10004;</td>'
                    else:
                        detail = r.get("detail", r.get("Detail", ""))
                        cells += f'<td class="fail" title="{_esc(detail)}">&#10008;</td>'
                rows_html += f"<tr>{cells}</tr>\n"

    # Header columns
    header_cells = "<th>Test</th>"
    for cid in ordered_clients:
        info = CLIENTS[cid]
        sdk = all_results[cid].get("sdk", "")
        p, f = totals[cid]
        color = "#3fb950" if f == 0 else "#f85149"
        source_link = info.get("source", "")
        src_html = f' <a href="{source_link}" target="_blank" title="View test source" style="color:#58a6ff;text-decoration:none">&#128279;</a>' if source_link else ""
        header_cells += (
            f'<th>{info["name"]}{src_html}<br>'
            f'<small>{sdk}</small><br>'
            f'<span style="color:{color};font-weight:bold">{p}/{p+f}</span></th>'
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
