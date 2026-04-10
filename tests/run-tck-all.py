#!/usr/bin/env python3
"""Run the A2A TCK against all server implementations and publish compatibility reports.

Usage:
    python tests/run-tck-all.py                     # Run TCK against all servers (must start each first)
    python tests/run-tck-all.py --server .NET       # Run against just .NET server
    python tests/run-tck-all.py --server Go         # Run against just Go server
    python tests/run-tck-all.py --publish           # Also copy compatibility pages to docs/

Prerequisites:
    - TCK venv at D:\\github\\a2aproject\\a2a-tck\\.venv
    - Each server running on its assigned port:
        .NET=5100, Go=5200, Python=5300, Rust=5400, Java=5000
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TCK_ROOT = Path(r'D:\github\a2aproject\a2a-tck')
TCK_PYTHON = TCK_ROOT / '.venv' / 'Scripts' / 'python.exe'
TCK_RUNNER = TCK_ROOT / 'run_tck.py'
DOCS_DIR = REPO_ROOT / 'docs'
TESTS_DIR = REPO_ROOT / 'tests'

# Server configs: name → (sut_host, transports)
# --sut-host is the base URL the TCK uses to discover /.well-known/agent.json
SERVERS = {
    '.NET':   {'url': 'http://localhost:5100/spec', 'transports': 'jsonrpc,http_json'},
    'Go':     {'url': 'http://localhost:5200/spec', 'transports': 'jsonrpc,http_json'},
    'Python': {'url': 'http://localhost:5300/spec', 'transports': 'jsonrpc,http_json'},
    'Rust':   {'url': 'http://localhost:5400/spec', 'transports': 'jsonrpc'},
    'Java':   {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc,http_json'},
}


def run_tck(server_name: str, sut_url: str, transports: str, results_dir: Path, publish: bool):
    """Run TCK against a server and copy reports to results_dir."""
    results_dir.mkdir(parents=True, exist_ok=True)
    tck_reports = TCK_ROOT / 'reports'

    # Clean the TCK reports dir to avoid stale results from previous runs
    if tck_reports.exists():
        for old in tck_reports.iterdir():
            if old.is_file():
                old.unlink(missing_ok=True)

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    cmd = [
        str(TCK_PYTHON), str(TCK_RUNNER),
        '--sut-host', sut_url,
        '--transport', transports,
    ]

    print(f'\n{"="*60}')
    print(f'Running TCK against {server_name} server')
    print(f'  SUT: {sut_url}')
    print(f'  Transports: {transports}')
    print(f'{"="*60}\n')

    result = subprocess.run(cmd, env=env, cwd=str(TCK_ROOT), capture_output=False)

    # Copy all report files from TCK reports dir
    copied = 0
    if tck_reports.exists():
        for src in sorted(tck_reports.iterdir()):
            if src.is_file():
                shutil.copy2(src, results_dir / src.name)
                copied += 1

    if copied:
        print(f'\n✅ {server_name}: Copied {copied} report files to {results_dir}')
    else:
        print(f'\n❌ {server_name}: No report files produced (exit code {result.returncode})')

    # Publish compatibility report to docs/
    server_slug = server_name.lower().replace('.', '')
    compat_src = results_dir / 'compatibility.html'
    if compat_src.exists():
        compat_dst = DOCS_DIR / f'compliance-{server_slug}.html'
        shutil.copy2(compat_src, compat_dst)
        print(f'  📄 Published {compat_dst.name}')

        if publish:
            # Also generate a combined compliance index if all servers are done
            pass


def main():
    parser = argparse.ArgumentParser(description='Run A2A TCK against all servers')
    parser.add_argument('--server', choices=list(SERVERS.keys()),
                        help='Run against a specific server only')
    parser.add_argument('--publish', action='store_true',
                        help='Copy compatibility pages to docs/')
    args = parser.parse_args()

    servers = {args.server: SERVERS[args.server]} if args.server else SERVERS

    for name, config in servers.items():
        run_tck(
            name,
            config['url'],
            config['transports'],
            TESTS_DIR / 'TCKResults' / name.lower().replace('.', ''),
            args.publish,
        )

    # Generate combined compliance index
    if args.publish:
        generate_compliance_index(servers)

    print('\n✅ Done!')


def generate_compliance_index(servers: dict):
    """Generate a simple index page linking to per-server compatibility reports."""
    links = []
    for name in servers:
        slug = name.lower().replace('.', '')
        fname = f'compliance-{slug}.html'
        fpath = DOCS_DIR / fname
        if fpath.exists():
            links.append(f'<li><a href="{fname}">{name} Server</a></li>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AgentBin TCK Compatibility Reports</title>
<style>
body {{ font-family: sans-serif; margin: 2em; background: #1a1a2e; color: #e0e0e0; }}
h1 {{ color: #00d4aa; }}
a {{ color: #4fc3f7; }}
ul {{ font-size: 1.2em; line-height: 2; }}
</style>
</head>
<body>
<h1>AgentBin TCK Compatibility Reports</h1>
<p>A2A Protocol Technology Compatibility Kit results per server implementation.</p>
<ul>
{''.join(links)}
</ul>
</body>
</html>"""

    index_path = DOCS_DIR / 'compliance.html'
    index_path.write_text(html, encoding='utf-8')
    print(f'  📄 Published {index_path.name}')


if __name__ == '__main__':
    main()
