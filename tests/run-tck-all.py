#!/usr/bin/env python3
"""Run the A2A TCK against all server implementations and generate compliance pages.

Usage:
    python tests/run-tck-all.py                     # Run TCK against all servers (must start each first)
    python tests/run-tck-all.py --server .NET       # Run against just .NET server
    python tests/run-tck-all.py --server Go         # Run against just Go server
    python tests/run-tck-all.py --publish            # Also copy compliance pages to docs/

Prerequisites:
    - TCK venv at D:\\github\\a2aproject\\a2a-tck\\.venv
    - Server running on the specified port (default 5100 for .NET, 5000 for others)
"""

import argparse
import json
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
COMPLIANCE_GENERATOR = TESTS_DIR / 'generate_compliance.py'

# Server configs: name → (sut_url, transports)
SERVERS = {
    '.NET':   {'url': 'http://localhost:5100/spec', 'transports': 'jsonrpc,rest'},
    'Go':     {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc,rest'},
    'Python': {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc,rest'},
    'Rust':   {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc'},
}


def run_tck(server_name: str, sut_url: str, transports: str, results_dir: Path) -> Path:
    """Run TCK against a server and return the compatibility.json path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / 'compatibility.json'
    report_html = results_dir / 'tck_report.html'

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    cmd = [
        str(TCK_PYTHON), str(TCK_RUNNER),
        '--sut-url', sut_url,
        '--transports', transports,
        '--category', 'all',
        '--compliance-report', str(report_path),
        '--report',
    ]

    print(f'\n{"="*60}')
    print(f'Running TCK against {server_name} server')
    print(f'  SUT: {sut_url}')
    print(f'  Transports: {transports}')
    print(f'  Output: {report_path}')
    print(f'{"="*60}\n')

    result = subprocess.run(cmd, env=env, cwd=str(TCK_ROOT), capture_output=False)

    # Copy the HTML report if generated
    tck_html = TCK_ROOT / 'reports' / 'tck_report.html'
    if tck_html.exists():
        shutil.copy2(tck_html, report_html)

    if not report_path.exists():
        # Fall back to TCK default output location
        default_report = TCK_ROOT / 'reports' / 'compatibility.json'
        if default_report.exists():
            shutil.copy2(default_report, report_path)

    if report_path.exists():
        d = json.loads(report_path.read_text(encoding='utf-8'))
        s = d.get('summary', {})
        print(f'\n✅ {server_name}: Overall {s.get("overall_compatibility", "?")}% '
              f'(MUST: {s.get("must_compatibility", "?")}%)')
    else:
        print(f'\n❌ {server_name}: No report generated (exit code {result.returncode})')

    return report_path


def generate_compliance(report_path: Path, server_name: str, publish: bool):
    """Generate compliance HTML from TCK JSON report."""
    server_slug = server_name.lower().replace('.', '')
    output = DOCS_DIR / f'compliance-{server_slug}.html'

    cmd = [
        sys.executable, str(COMPLIANCE_GENERATOR),
        str(report_path), str(output),
        '--server', server_name,
    ]
    if publish:
        cmd.append('--publish')

    subprocess.run(cmd, check=True)
    print(f'Generated {output.name}')


def main():
    parser = argparse.ArgumentParser(description='Run A2A TCK against all servers')
    parser.add_argument('--server', choices=list(SERVERS.keys()),
                        help='Run against a specific server only')
    parser.add_argument('--publish', action='store_true',
                        help='Copy compliance pages to docs/')
    parser.add_argument('--generate-only', action='store_true',
                        help='Skip TCK run, just regenerate HTML from existing results')
    args = parser.parse_args()

    servers = {args.server: SERVERS[args.server]} if args.server else SERVERS

    for name, config in servers.items():
        slug = name.lower().replace('.', '')
        results_dir = TESTS_DIR / f'TCKResults' / slug

        if not args.generate_only:
            report_path = run_tck(name, config['url'], config['transports'], results_dir)
        else:
            report_path = results_dir / 'compatibility.json'

        if report_path.exists():
            generate_compliance(report_path, name, args.publish)
        else:
            print(f'⚠️  No results for {name} — skipping compliance generation')

    print('\n✅ Done!')


if __name__ == '__main__':
    main()
