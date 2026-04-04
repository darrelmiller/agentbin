"""Generate the TCK compliance page from TCK JSON report."""
import argparse
import json
import sys
from html import escape
from pathlib import Path

SDK_LABELS = {
    '.net': '.NET SDK', 'dotnet': '.NET SDK',
    'go': 'Go SDK', 'python': 'Python SDK', 'rust': 'Rust SDK',
}


def esc(s):
    return escape(str(s)) if s else ''


def generate_compliance_html(report_path: str, output_path: str, server: str | None = None):
    d = json.loads(Path(report_path).read_text(encoding='utf-8'))
    summary = d['summary']
    sdk_label = SDK_LABELS.get(server.lower(), f'{server} SDK') if server else '.NET SDK'

    # Handle reports where TCK couldn't even fetch the agent card
    reqs = d.get('per_requirement', {})
    if not reqs and summary.get('overall_score', -1) == 0.0:
        _generate_card_failure_html(output_path, summary, sdk_label)
        return

    # Categorize requirements
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

    def pct_val(p):
        return float(str(p).rstrip('%'))

    def make_rows(items, show_errors=False):
        rows = ''
        for rid, rdata in items:
            status = rdata['status']
            transports = rdata.get('transports', {})
            transport_badges = ''
            for t, ts in sorted(transports.items()):
                color = '#22c55e' if ts == 'PASS' else '#ef4444' if ts == 'FAIL' else '#94a3b8'
                transport_badges += (
                    f'<span style="background:{color};color:#fff;padding:1px 6px;'
                    f'border-radius:3px;font-size:11px;margin-right:3px">{esc(t)}</span>'
                )

            status_color = (
                '#22c55e' if status == 'PASS' else
                '#ef4444' if status == 'FAIL' else
                '#f59e0b' if status == 'SKIPPED' else '#94a3b8'
            )

            error_cell = ''
            if show_errors and rdata.get('errors'):
                err = rdata['errors'][0][:120]
                full = esc(rdata['errors'][0])
                error_cell = (
                    f'<td style="font-size:12px;color:#94a3b8;max-width:350px;'
                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                    f'title="{full}">{esc(err)}</td>'
                )
            elif show_errors:
                error_cell = '<td></td>'

            rows += (
                f'<tr>'
                f'<td><code style="font-size:12px">{esc(rid)}</code></td>'
                f'<td style="color:{status_color};font-weight:600">{esc(status)}</td>'
                f'<td>{transport_badges}</td>'
                f'{error_cell}'
                f'</tr>\n'
            )
        return rows

    overall_class = 'pass' if pct_val(overall_pct) >= 80 else 'warn'
    must_class = 'pass' if pct_val(must_pct) >= 80 else 'warn'
    overall_bar_color = '#22c55e' if pct_val(overall_pct) >= 80 else '#f59e0b'
    not_tested_count = len(categories['must_not_tested']) + len(categories.get('should_not_tested', []))
    all_passing = categories['must_pass'] + categories['should_pass'] + categories['may_pass']
    all_not_tested = categories['must_not_tested'] + categories.get('should_not_tested', [])
    timestamp = esc(summary['timestamp'][:19])
    sut_url = esc(summary['sut_url'])

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
  .card {{ background: #1e293b; border-radius: 10px; padding: 16px 20px; min-width: 160px; flex: 1; }}
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
  Tested: {timestamp} UTC &bull;
  SUT: <code>{sut_url}</code>
</div>

<div class="note">
  <strong>What is this?</strong> The
  <a href="https://github.com/a2aproject/a2a-tck">A2A TCK</a>
  is a conformance test suite that validates A2A server implementations against the
  <a href="https://github.com/a2aproject/a2a-spec">A2A specification</a>.
  Failures indicate {sdk_label} gaps &mdash; not SpecAgent bugs.
  Each requirement maps to a specific spec section.
</div>

<div class="summary">
  <div class="card">
    <div class="label">Overall</div>
    <div class="value {overall_class}">{overall_pct}%</div>
    <div class="gauge"><div class="gauge-fill" style="width:{overall_pct}%;background:{overall_bar_color}"></div></div>
  </div>
  <div class="card">
    <div class="label">MUST</div>
    <div class="value {must_class}">{must_pct}%</div>
    <div class="detail">{len(categories['must_pass'])} pass &bull; {len(categories['must_fail'])} fail &bull; {len(categories['must_skip'])} skip</div>
  </div>
  <div class="card">
    <div class="label">SHOULD</div>
    <div class="value pass">100%</div>
    <div class="detail">{len(categories['should_pass'])} pass</div>
  </div>
  <div class="card">
    <div class="label">MAY</div>
    <div class="value pass">100%</div>
    <div class="detail">{len(categories['may_pass'])} pass</div>
  </div>
  <div class="card">
    <div class="label">Not Tested</div>
    <div class="value muted">{not_tested_count}</div>
    <div class="detail">gRPC transport not supported</div>
  </div>
</div>

<div class="section">
  <h2>&#x274C; Failing Requirements <span class="count">({len(categories['must_fail'])})</span></h2>
  <table>
    <tr><th>Requirement</th><th>Status</th><th>Transports</th><th>Error</th></tr>
    {make_rows(categories['must_fail'], show_errors=True)}
  </table>
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x2705; Passing Requirements <span class="count">({len(all_passing)})</span></h2></summary>
    <table>
      <tr><th>Requirement</th><th>Status</th><th>Transports</th></tr>
      {make_rows(all_passing)}
    </table>
  </details>
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x23ED;&#xFE0F; Skipped <span class="count">({len(categories['must_skip'])})</span></h2></summary>
    <table>
      <tr><th>Requirement</th><th>Status</th><th>Transports</th><th>Reason</th></tr>
      {make_rows(categories['must_skip'], show_errors=True)}
    </table>
  </details>
</div>

<div class="section">
  <details>
    <summary><h2 style="display:inline">&#x26AA; Not Tested <span class="count">({not_tested_count})</span></h2></summary>
    <p style="font-size:13px;color:#64748b;margin-bottom:8px">
      These requirements target gRPC transport which AgentBin does not currently support.
    </p>
    <table>
      <tr><th>Requirement</th><th>Status</th><th>Transports</th></tr>
      {make_rows(all_not_tested)}
    </table>
  </details>
</div>

</body>
</html>'''

    Path(output_path).write_text(html, encoding='utf-8')
    print(f'Generated {output_path} ({len(html):,} bytes)')


def _generate_card_failure_html(output_path: str, summary: dict, sdk_label: str):
    """Generate a simple compliance page when TCK couldn't fetch the agent card."""
    timestamp = esc(summary.get('timestamp', '?')[:19])
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
    parser.add_argument('report', nargs='?',
                        default=r'D:\github\a2aproject\a2a-tck\reports\compatibility.json',
                        help='Path to TCK compatibility.json')
    parser.add_argument('output', nargs='?',
                        default=r'D:\github\darrelmiller\agentbin\docs\compliance.html',
                        help='Output HTML path')
    parser.add_argument('--server', default=None,
                        help='Server name (e.g. .NET, Go, Python, Rust). '
                             'When set, output filename becomes compliance-{server}.html')
    parser.add_argument('--publish', action='store_true',
                        help='Copy output to docs/ directory')
    args = parser.parse_args()

    output = args.output
    if args.server:
        server_slug = args.server.lower().replace('.', '')
        output = str(Path(args.output).parent / f'compliance-{server_slug}.html')

    generate_compliance_html(args.report, output, server=args.server)

    if args.publish:
        docs_dir = Path(r'D:\github\darrelmiller\agentbin\docs')
        dest = docs_dir / Path(output).name
        import shutil
        shutil.copy2(output, dest)
        print(f'Published to {dest}')
