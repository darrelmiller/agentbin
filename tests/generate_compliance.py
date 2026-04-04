"""Generate TCK compliance pages from pytest-json-report files.

Reads the per-category result JSON files produced by the TCK's pytest runs
and generates a dark-themed HTML compliance dashboard.

Usage:
    python tests/generate_compliance.py --results-dir reports/ --server .NET --output docs/compliance-net.html
    python tests/generate_compliance.py --results-dir reports/ --server Go   --output docs/compliance-go.html
"""
import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

SDK_LABELS = {
    '.net': '.NET SDK', 'dotnet': '.NET SDK', 'net': '.NET SDK',
    'go': 'Go SDK', 'python': 'Python SDK', 'rust': 'Rust SDK',
}


def esc(s):
    return escape(str(s)) if s else ''


def _parse_results_dir(results_dir: str) -> dict:
    """Parse all *_results.json files in a directory into a unified structure."""
    results_dir = Path(results_dir)
    all_tests = []
    earliest_ts = None

    for fpath in sorted(results_dir.glob('*_results.json')):
        fname = fpath.stem  # e.g. "mandatory_jsonrpc_results"
        data = json.loads(fpath.read_text(encoding='utf-8'))

        # Track earliest timestamp
        created = data.get('created')
        if created and (earliest_ts is None or created < earliest_ts):
            earliest_ts = created

        # Determine category and transport from filename
        # Patterns: mandatory_jsonrpc_results, capabilities_rest_results,
        #           transport-equivalence_results
        parts = fname.replace('_results', '').rsplit('_', 1)
        if len(parts) == 2 and parts[1] in ('jsonrpc', 'rest'):
            category, transport = parts
        else:
            category = parts[0]
            transport = 'multi'

        for test in data.get('tests', []):
            # Extract readable test name from nodeid
            nodeid = test.get('nodeid', '')
            test_name = nodeid.split('::')[-1] if '::' in nodeid else nodeid
            test_module = nodeid.split('::')[0].split('/')[-1].replace('.py', '') if '/' in nodeid else ''

            outcome = test.get('outcome', 'unknown')

            # Extract error/skip reason
            error_msg = ''
            # Check call phase first (for failed tests)
            call = test.get('call', {})
            if call:
                if call.get('crash', {}).get('message'):
                    error_msg = call['crash']['message']
                elif call.get('longrepr'):
                    lines = str(call['longrepr']).strip().split('\n')
                    error_msg = lines[-1][:200] if lines else ''

            # For error tests, check setup phase (collection/fixture errors)
            if not error_msg and outcome == 'error':
                setup = test.get('setup', {})
                if setup.get('crash', {}).get('message'):
                    error_msg = setup['crash']['message']
                elif setup.get('longrepr'):
                    lines = str(setup['longrepr']).strip().split('\n')
                    error_msg = lines[-1][:200] if lines else ''

            # For skipped tests, extract reason from setup.longrepr
            if outcome == 'skipped' and not error_msg:
                setup = test.get('setup', {})
                longrepr = setup.get('longrepr')
                if isinstance(longrepr, str):
                    error_msg = longrepr
                elif isinstance(longrepr, (list, tuple)) and len(longrepr) >= 3:
                    error_msg = str(longrepr[2])

            all_tests.append({
                'name': test_name,
                'module': test_module,
                'nodeid': nodeid,
                'category': category,
                'transport': transport,
                'outcome': outcome,
                'error': error_msg,
            })

    timestamp = datetime.fromtimestamp(earliest_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if earliest_ts else '?'
    return {'tests': all_tests, 'timestamp': timestamp}


def _group_tests(tests: list) -> dict:
    """Group tests by function name, collecting transport results per test."""
    grouped = {}
    for t in tests:
        key = (t['category'], t['name'])
        if key not in grouped:
            grouped[key] = {
                'name': t['name'],
                'module': t['module'],
                'category': t['category'],
                'transports': {},
                'error': t['error'],
                'worst_outcome': t['outcome'],
            }
        grouped[key]['transports'][t['transport']] = t['outcome']
        # Worst outcome: error > failed > skipped > passed
        rank = {'error': 0, 'failed': 1, 'skipped': 2, 'passed': 3}
        if rank.get(t['outcome'], 4) < rank.get(grouped[key]['worst_outcome'], 4):
            grouped[key]['worst_outcome'] = t['outcome']
            if t['error']:
                grouped[key]['error'] = t['error']
    return grouped


def generate_compliance_html(results_dir: str, output_path: str, server: str | None = None):
    sdk_label = SDK_LABELS.get(server.lower(), f'{server} SDK') if server else 'SDK'
    parsed = _parse_results_dir(results_dir)
    tests = parsed['tests']
    timestamp = parsed['timestamp']

    if not tests:
        _generate_card_failure_html(output_path, {'timestamp': timestamp, 'compliance_level': 'NO_RESULTS'}, sdk_label)
        return

    # Group by test function to deduplicate across transports
    grouped = _group_tests(tests)

    # Categorize
    categories_map = defaultdict(list)
    for key, g in sorted(grouped.items()):
        cat = g['category']
        outcome = g['worst_outcome']
        categories_map[f'{cat}_{outcome}'].append(g)

    # Compute stats
    all_grouped = list(grouped.values())
    passed = [g for g in all_grouped if g['worst_outcome'] == 'passed']
    failed = [g for g in all_grouped if g['worst_outcome'] == 'failed']
    errored = [g for g in all_grouped if g['worst_outcome'] == 'error']
    skipped = [g for g in all_grouped if g['worst_outcome'] == 'skipped']

    total_testable = len(passed) + len(failed) + len(errored)
    overall_pct = round(100 * len(passed) / total_testable, 1) if total_testable else 0

    # Mandatory stats
    mandatory = [g for g in all_grouped if g['category'] == 'mandatory']
    m_passed = [g for g in mandatory if g['worst_outcome'] == 'passed']
    m_failed = [g for g in mandatory if g['worst_outcome'] in ('failed', 'error')]
    m_skipped = [g for g in mandatory if g['worst_outcome'] == 'skipped']
    m_total = len(m_passed) + len(m_failed)
    mandatory_pct = round(100 * len(m_passed) / m_total, 1) if m_total else 0

    # Capabilities stats
    caps = [g for g in all_grouped if g['category'] == 'capabilities']
    c_passed = [g for g in caps if g['worst_outcome'] == 'passed']
    c_failed = [g for g in caps if g['worst_outcome'] in ('failed', 'error')]
    c_total = len(c_passed) + len(c_failed)
    caps_pct = round(100 * len(c_passed) / c_total, 1) if c_total else 0

    overall_class = 'pass' if overall_pct >= 70 else 'warn' if overall_pct >= 40 else 'fail'
    mandatory_class = 'pass' if mandatory_pct >= 70 else 'warn' if mandatory_pct >= 40 else 'fail'
    caps_class = 'pass' if caps_pct >= 70 else 'warn' if caps_pct >= 40 else 'fail'
    bar_color = '#22c55e' if overall_pct >= 70 else '#f59e0b' if overall_pct >= 40 else '#ef4444'

    def transport_badges(transports: dict) -> str:
        badges = ''
        for t, outcome in sorted(transports.items()):
            if outcome == 'passed':
                color = '#22c55e' if t == 'jsonrpc' else '#3b82f6'
            elif outcome in ('failed', 'error'):
                color = '#ef4444'
            else:
                color = '#94a3b8'
            label = t if t != 'multi' else 'cross-transport'
            badges += (f'<span style="background:{color};color:#fff;padding:1px 6px;'
                       f'border-radius:3px;font-size:11px;margin-right:3px">{esc(label)}</span>')
        return badges

    def cat_badge(category: str) -> str:
        colors = {'mandatory': '#3b82f6', 'capabilities': '#8b5cf6',
                  'quality': '#f59e0b', 'features': '#22d3ee',
                  'transport-equivalence': '#ec4899'}
        c = colors.get(category, '#64748b')
        return (f'<span style="background:{c};color:#fff;padding:1px 6px;'
                f'border-radius:3px;font-size:11px;margin-right:3px">{esc(category)}</span>')

    def make_rows(items, show_errors=False):
        rows = ''
        for g in items:
            status = g['worst_outcome']
            status_color = {'passed': '#22c55e', 'failed': '#ef4444',
                            'error': '#ef4444', 'skipped': '#f59e0b'}.get(status, '#94a3b8')
            error_cell = ''
            if show_errors:
                err = esc(g.get('error', '')[:150])
                full = esc(g.get('error', ''))
                error_cell = (f'<td style="font-size:12px;color:#94a3b8;max-width:350px;'
                              f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                              f'title="{full}">{err}</td>')
            rows += (f'<tr>'
                     f'<td><code style="font-size:12px">{esc(g["name"])}</code></td>'
                     f'<td>{cat_badge(g["category"])}</td>'
                     f'<td>{transport_badges(g["transports"])}</td>'
                     f'{error_cell}'
                     f'</tr>\n')
        return rows

    all_failures = failed + errored

    # Build collapsible per-category failing sections
    fail_categories = []
    for cat in ['mandatory', 'capabilities', 'quality', 'features', 'transport-equivalence']:
        cat_fails = [g for g in all_failures if g['category'] == cat]
        if cat_fails:
            fail_categories.append((cat, cat_fails))

    fail_section_html = ''
    if fail_categories:
        for cat, cat_fails in fail_categories:
            fail_section_html += (
                f'<details open>\n'
                f'<summary style="margin-bottom:8px">{cat_badge(cat)} '
                f'<span style="color:#94a3b8;font-size:13px">{len(cat_fails)} failing</span></summary>\n'
                f'<table>\n'
                f'<tr><th>Test</th><th>Category</th><th>Transport</th><th>Error</th></tr>\n'
                f'{make_rows(cat_fails, show_errors=True)}'
                f'</table>\n</details>\n'
            )
    else:
        fail_section_html = '<p style="color:#64748b">No failing tests!</p>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentBin — Server Compliance (TCK)</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 13px; margin-bottom: 20px; }}
  .subtitle a {{ color: #38bdf8; }}
  .summary {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 16px 20px; min-width: 140px; flex: 1; }}
  .card .label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
  .card .detail {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
  .pass {{ color: #22c55e; }}
  .fail {{ color: #ef4444; }}
  .warn {{ color: #f59e0b; }}
  .muted {{ color: #64748b; }}
  .gauge {{ width: 100%; height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
  .gauge-fill {{ height: 100%; border-radius: 4px; }}
  .section {{ background: #1e293b; border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }}
  .section h2 {{ font-size: 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }}
  .section h2 .count {{ font-size: 13px; color: #64748b; font-weight: 400; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
       color: #64748b; padding: 6px 8px; border-bottom: 1px solid #334155; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #1e293b; font-size: 13px; }}
  tr:hover {{ background: #334155; }}
  details {{ cursor: pointer; }}
  details summary {{ font-weight: 600; padding: 4px 0; }}
  details summary:hover {{ color: #38bdf8; }}
  .note {{ background: #1e293b; border-left: 3px solid #3b82f6; padding: 12px 16px;
           margin-bottom: 16px; border-radius: 0 8px 8px 0; font-size: 13px; color: #94a3b8; }}
  .note strong {{ color: #e2e8f0; }}
  .note a {{ color: #38bdf8; }}
</style>
</head>
<body>

<h1>&#x1F9EA; Server Compliance &mdash; A2A TCK</h1>
<div class="subtitle">
  A2A Test Compatibility Kit results for AgentBin SpecAgent ({sdk_label}) &bull;
  Tested: {timestamp} UTC
</div>

<div class="note">
  <strong>What is this?</strong> The
  <a href="https://github.com/a2aproject/a2a-tck">A2A TCK</a>
  is a conformance test suite that validates A2A server implementations against the
  <a href="https://github.com/a2aproject/a2a-spec">A2A specification</a>.
  Failures indicate {sdk_label} gaps &mdash; not SpecAgent bugs.
</div>

<div class="summary">
  <div class="card">
    <div class="label">Overall</div>
    <div class="value {overall_class}">{overall_pct}%</div>
    <div class="detail">{len(passed)} pass &bull; {len(all_failures)} fail &bull; {len(skipped)} skip</div>
    <div class="gauge"><div class="gauge-fill" style="width:{overall_pct}%;background:{bar_color}"></div></div>
  </div>
  <div class="card">
    <div class="label">Mandatory</div>
    <div class="value {mandatory_class}">{mandatory_pct}%</div>
    <div class="detail">{len(m_passed)} pass &bull; {len(m_failed)} fail &bull; {len(m_skipped)} skip</div>
  </div>
  <div class="card">
    <div class="label">Capabilities</div>
    <div class="value {caps_class}">{caps_pct}%</div>
    <div class="detail">{len(c_passed)} pass &bull; {len(c_failed)} fail</div>
  </div>
  <div class="card">
    <div class="label">Skipped</div>
    <div class="value muted">{len(skipped)}</div>
    <div class="detail">auth, gRPC, etc.</div>
  </div>
</div>

<div class="section">
  <h2>&#x274C; Failing Tests <span class="count">({len(all_failures)})</span></h2>
  {fail_section_html}
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x2705; Passing Tests <span class="count">({len(passed)})</span></h2></summary>
    <table>
      <tr><th>Test</th><th>Category</th><th>Transport</th></tr>
      {make_rows(passed)}
    </table>
  </details>
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x23ED;&#xFE0F; Skipped <span class="count">({len(skipped)})</span></h2></summary>
    <table>
      <tr><th>Test</th><th>Category</th><th>Transport</th><th>Reason</th></tr>
      {make_rows(skipped, show_errors=True)}
    </table>
  </details>
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x26A0;&#xFE0F; Errors <span class="count">({len(errored)})</span></h2></summary>
    <table>
      <tr><th>Test</th><th>Category</th><th>Transport</th><th>Error</th></tr>
      {make_rows(errored, show_errors=True)}
    </table>
  </details>
</div>

</body>
</html>'''

    Path(output_path).write_text(html, encoding='utf-8')
    print(f'Generated {output_path} ({len(html):,} bytes) — {overall_pct}% overall, {mandatory_pct}% mandatory')


def _generate_legacy_html(report_path: str, output_path: str, server: str | None = None):
    """Generate compliance HTML from legacy TCK compatibility.json with per_requirement."""
    d = json.loads(Path(report_path).read_text(encoding='utf-8'))
    summary = d['summary']
    sdk_label = SDK_LABELS.get(server.lower(), f'{server} SDK') if server else '.NET SDK'

    reqs = d.get('per_requirement', {})
    if not reqs and summary.get('overall_score', -1) == 0.0:
        _generate_card_failure_html(output_path, summary, sdk_label)
        return

    categories: dict[str, list] = {
        'must_pass': [], 'must_fail': [], 'must_skip': [], 'must_not_tested': [],
        'should_pass': [], 'should_not_tested': [],
        'may_pass': [], 'may_not_tested': []
    }
    for rid, rdata in sorted(reqs.items()):
        level = rdata['level'].lower()
        status = rdata['status'].lower().replace(' ', '_')
        key = f"{level}_{status}"
        if key in categories:
            categories[key].append((rid, rdata))
        elif 'not_tested' in status or 'not tested' in rdata['status'].lower():
            categories.setdefault(f"{level}_not_tested", []).append((rid, rdata))

    must_pct = summary['must_compatibility']
    overall_pct = summary['overall_compatibility']
    pct_val = lambda p: float(str(p).rstrip('%'))

    def make_legacy_rows(items, show_errors=False):
        rows = ''
        for rid, rdata in items:
            status = rdata['status']
            transports = rdata.get('transports', {})
            tbadges = ''
            for t, ts in sorted(transports.items()):
                color = '#22c55e' if ts == 'PASS' else '#ef4444' if ts == 'FAIL' else '#94a3b8'
                tbadges += (f'<span style="background:{color};color:#fff;padding:1px 6px;'
                            f'border-radius:3px;font-size:11px;margin-right:3px">{esc(t)}</span>')
            status_color = ('#22c55e' if status == 'PASS' else '#ef4444' if status == 'FAIL'
                            else '#f59e0b' if status == 'SKIPPED' else '#94a3b8')
            error_cell = ''
            if show_errors and rdata.get('errors'):
                error_cell = (f'<td style="font-size:12px;color:#94a3b8;max-width:350px;'
                              f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                              f'title="{esc(rdata["errors"][0])}">{esc(rdata["errors"][0][:120])}</td>')
            elif show_errors:
                error_cell = '<td></td>'
            rows += (f'<tr><td><code style="font-size:12px">{esc(rid)}</code></td>'
                     f'<td style="color:{status_color};font-weight:600">{esc(status)}</td>'
                     f'<td>{tbadges}</td>{error_cell}</tr>\n')
        return rows

    overall_class = 'pass' if pct_val(overall_pct) >= 80 else 'warn'
    must_class = 'pass' if pct_val(must_pct) >= 80 else 'warn'
    bar_color = '#22c55e' if pct_val(overall_pct) >= 80 else '#f59e0b'
    not_tested_count = len(categories['must_not_tested']) + len(categories.get('should_not_tested', []))
    all_passing = categories['must_pass'] + categories['should_pass'] + categories['may_pass']
    all_not_tested = categories['must_not_tested'] + categories.get('should_not_tested', [])
    timestamp = esc(summary['timestamp'][:19])
    sut_url = esc(summary['sut_url'])

    html = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentBin &mdash; Server Compliance (TCK)</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0f172a; color:#e2e8f0; padding:24px; }}
  h1 {{ font-size:22px; margin-bottom:4px; }}
  .subtitle {{ color:#94a3b8; font-size:13px; margin-bottom:20px; }}
  .summary {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px; }}
  .card {{ background:#1e293b; border-radius:10px; padding:16px 20px; min-width:140px; flex:1; }}
  .card .label {{ font-size:12px; color:#94a3b8; text-transform:uppercase; }}
  .card .value {{ font-size:28px; font-weight:700; margin-top:4px; }}
  .card .detail {{ font-size:12px; color:#64748b; margin-top:2px; }}
  .pass {{ color:#22c55e; }} .fail {{ color:#ef4444; }} .warn {{ color:#f59e0b; }} .muted {{ color:#64748b; }}
  .gauge {{ width:100%; height:8px; background:#334155; border-radius:4px; overflow:hidden; margin-top:8px; }}
  .gauge-fill {{ height:100%; border-radius:4px; }}
  .section {{ background:#1e293b; border-radius:10px; padding:16px 20px; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; font-size:11px; color:#64748b; padding:6px 8px; border-bottom:1px solid #334155; }}
  td {{ padding:6px 8px; border-bottom:1px solid #1e293b; font-size:13px; }}
  tr:hover {{ background:#334155; }}
  details {{ cursor:pointer; }} details summary {{ font-weight:600; padding:4px 0; }}
  .note {{ background:#1e293b; border-left:3px solid #3b82f6; padding:12px 16px;
           margin-bottom:16px; border-radius:0 8px 8px 0; font-size:13px; color:#94a3b8; }}
  .note strong {{ color:#e2e8f0; }} .note a {{ color:#38bdf8; }}
</style></head><body>
<h1>&#x1F9EA; Server Compliance &mdash; A2A TCK</h1>
<div class="subtitle">AgentBin SpecAgent ({sdk_label}) &bull; {timestamp} UTC &bull; SUT: <code>{sut_url}</code></div>
<div class="summary">
  <div class="card"><div class="label">Overall</div><div class="value {overall_class}">{overall_pct}%</div>
    <div class="gauge"><div class="gauge-fill" style="width:{overall_pct}%;background:{bar_color}"></div></div></div>
  <div class="card"><div class="label">MUST</div><div class="value {must_class}">{must_pct}%</div>
    <div class="detail">{len(categories['must_pass'])} pass &bull; {len(categories['must_fail'])} fail</div></div>
  <div class="card"><div class="label">Not Tested</div><div class="value muted">{not_tested_count}</div></div>
</div>
<div class="section"><h2>&#x274C; Failing ({len(categories['must_fail'])})</h2>
<table><tr><th>Requirement</th><th>Status</th><th>Transports</th><th>Error</th></tr>
{make_legacy_rows(categories['must_fail'], show_errors=True)}</table></div>
<div class="section"><details><summary>&#x2705; Passing ({len(all_passing)})</summary>
<table><tr><th>Requirement</th><th>Status</th><th>Transports</th></tr>
{make_legacy_rows(all_passing)}</table></details></div>
</body></html>'''
    Path(output_path).write_text(html, encoding='utf-8')
    print(f'Generated {output_path} ({len(html):,} bytes)')


def _generate_card_failure_html(output_path: str, summary: dict, sdk_label: str):
    """Generate a simple compliance page when TCK couldn't fetch the agent card."""
    timestamp = esc(str(summary.get('timestamp', '?'))[:19])
    level = esc(summary.get('compliance_level', 'NON_COMPLIANT'))
    html = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentBin — Server Compliance (TCK)</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0f172a; color:#e2e8f0; padding:24px; }}
  h1 {{ font-size:22px; margin-bottom:4px; }}
  .subtitle {{ color:#94a3b8; font-size:13px; margin-bottom:20px; }}
  .card {{ background:#1e293b; border-radius:10px; padding:16px 20px; margin-bottom:16px; }}
  .fail {{ color:#ef4444; }}
  .note {{ background:#1e293b; border-left:3px solid #ef4444; padding:12px 16px;
           margin-bottom:16px; border-radius:0 8px 8px 0; font-size:13px; color:#94a3b8; }}
  .note strong {{ color:#e2e8f0; }}
</style>
</head><body>
<h1>&#x1F9EA; Server Compliance &mdash; A2A TCK</h1>
<div class="subtitle">A2A TCK results for AgentBin SpecAgent ({sdk_label}) &bull; Tested: {timestamp} UTC</div>
<div class="card">
  <div style="font-size:28px;font-weight:700" class="fail">0%</div>
  <div style="font-size:12px;color:#64748b;margin-top:4px">{level}</div>
</div>
<div class="note">
  <strong>Agent Card Fetch Failed</strong><br>
  The TCK could not fetch or parse the agent card from this server.
  This typically indicates the {sdk_label} produces an agent card with non-standard
  field names or JSON structure that the TCK cannot parse.<br><br>
  <strong>Common causes:</strong> lowercase enum values instead of UPPER_CASE,
  non-standard <code>kind</code> fields, missing required card fields,
  or non-standard JSON-RPC endpoint paths.
</div>
</body></html>'''
    Path(output_path).write_text(html, encoding='utf-8')
    print(f'Generated {output_path} (card-failure mode, {len(html):,} bytes)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate TCK compliance HTML page')
    parser.add_argument('report', nargs='?', default=None,
                        help='(Legacy) Path to TCK compatibility.json or results directory')
    parser.add_argument('--results-dir', default=None,
                        help='Directory containing *_results.json files from TCK')
    parser.add_argument('--server', default=None,
                        help='Server name (e.g. .NET, Go, Python, Rust)')
    parser.add_argument('--output', '-o', default=None,
                        help='Output HTML path (default: docs/compliance-{server}.html)')
    parser.add_argument('--publish', action='store_true',
                        help='Copy output to docs/ directory')
    args = parser.parse_args()

    docs_dir = Path(r'D:\github\darrelmiller\agentbin\docs')
    server_slug = args.server.lower().replace('.', '') if args.server else 'unknown'
    output = args.output or str(docs_dir / f'compliance-{server_slug}.html')

    if args.results_dir:
        # New mode: directory of pytest-json-report files
        generate_compliance_html(args.results_dir, output, server=args.server)
    elif args.report:
        rpath = Path(args.report)
        if rpath.is_dir():
            # Positional arg is a directory — treat as results dir
            generate_compliance_html(str(rpath), output, server=args.server)
        elif rpath.is_file():
            d = json.loads(rpath.read_text(encoding='utf-8'))
            if 'per_requirement' in d:
                # Legacy compatibility.json with per_requirement format
                _generate_legacy_html(args.report, output, server=args.server)
            elif isinstance(d.get('tests'), list):
                # Single pytest-json-report file; treat parent dir as results dir
                generate_compliance_html(str(rpath.parent), output, server=args.server)
            else:
                _generate_legacy_html(args.report, output, server=args.server)
        else:
            print(f'Error: {args.report} not found', file=sys.stderr)
            sys.exit(1)
    else:
        # Default: try TCK reports directory
        default_dir = r'D:\github\a2aproject\a2a-tck\reports'
        if Path(default_dir).is_dir():
            generate_compliance_html(default_dir, output, server=args.server)
        else:
            parser.print_help()
            sys.exit(1)

    if args.publish:
        docs_dir = Path(r'D:\github\darrelmiller\agentbin\docs')
        dest = docs_dir / Path(output).name
        shutil.copy2(output, dest)
        print(f'Published to {dest}')

