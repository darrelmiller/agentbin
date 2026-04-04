#!/usr/bin/env python3
"""Run the A2A TCK against all server implementations and generate compliance pages.

Usage:
    python tests/run-tck-all.py                     # Run TCK against all servers (must start each first)
    python tests/run-tck-all.py --server .NET       # Run against just .NET server
    python tests/run-tck-all.py --server Go         # Run against just Go server
    python tests/run-tck-all.py --publish            # Also copy compliance pages to docs/
    python tests/run-tck-all.py --generate-only --publish  # Regenerate HTML from saved results

Prerequisites:
    - TCK venv at D:\\github\\a2aproject\\a2a-tck\\.venv
    - Server running on the specified port (default 5100 for .NET, 5000 for others)
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
COMPLIANCE_GENERATOR = TESTS_DIR / 'generate_compliance.py'

# Server configs: name → (sut_url, transports)
SERVERS = {
    '.NET':   {'url': 'http://localhost:5100/spec', 'transports': 'jsonrpc,rest'},
    'Go':     {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc,rest'},
    'Python': {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc,rest'},
    'Rust':   {'url': 'http://localhost:5000/spec', 'transports': 'jsonrpc'},
    'Java':   {'url': 'http://localhost:5000', 'transports': 'jsonrpc,rest'},
}


def run_tck(server_name: str, sut_url: str, transports: str, results_dir: Path):
    """Run TCK against a server and copy raw result files to results_dir."""
    results_dir.mkdir(parents=True, exist_ok=True)
    tck_reports = TCK_ROOT / 'reports'

    # Clean the TCK reports dir to avoid stale results from previous runs
    for old in tck_reports.glob('*_results.json'):
        old.unlink(missing_ok=True)

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    # Pass --compliance-report to a dummy path to prevent the TCK from
    # deleting the raw JSON result files after the run completes.
    # (The TCK's cleanup code deletes them when no compliance report is requested.)
    dummy_compliance = results_dir / '_compliance_dummy.json'
    cmd = [
        str(TCK_PYTHON), str(TCK_RUNNER),
        '--sut-url', sut_url,
        '--transports', transports,
        '--category', 'all',
        '--report',
        '--compliance-report', str(dummy_compliance),
    ]

    print(f'\n{"="*60}')
    print(f'Running TCK against {server_name} server')
    print(f'  SUT: {sut_url}')
    print(f'  Transports: {transports}')
    print(f'{"="*60}\n')

    result = subprocess.run(cmd, env=env, cwd=str(TCK_ROOT), capture_output=False)

    # Copy all *_results.json files from TCK reports dir
    copied = 0
    for src in sorted(tck_reports.glob('*_results.json')):
        shutil.copy2(src, results_dir / src.name)
        copied += 1

    # Clean up dummy compliance file
    dummy_compliance = results_dir / '_compliance_dummy.json'
    dummy_compliance.unlink(missing_ok=True)

    if copied:
        print(f'\n✅ {server_name}: Copied {copied} result files to {results_dir}')
    else:
        print(f'\n❌ {server_name}: No result files produced (exit code {result.returncode})')


def generate_compliance(results_dir: Path, server_name: str, publish: bool):
    """Generate compliance HTML from raw pytest JSON report files."""
    server_slug = server_name.lower().replace('.', '')
    output = DOCS_DIR / f'compliance-{server_slug}.html'

    cmd = [
        sys.executable, str(COMPLIANCE_GENERATOR),
        '--results-dir', str(results_dir),
        '--server', server_name,
        '--output', str(output),
    ]
    if publish:
        cmd.append('--publish')

    subprocess.run(cmd, check=True)


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
        results_dir = TESTS_DIR / 'TCKResults' / slug

        if not args.generate_only:
            run_tck(name, config['url'], config['transports'], results_dir)

        # Check if result files exist
        result_files = list(results_dir.glob('*_results.json'))
        if result_files:
            generate_compliance(results_dir, name, args.publish)
        else:
            print(f'⚠️  No results for {name} — skipping compliance generation')

    print('\n✅ Done!')


if __name__ == '__main__':
    main()
