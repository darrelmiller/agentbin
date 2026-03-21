#!/usr/bin/env python3
"""
AgentBin Smoke Test — Post-Deployment Health Check

Verifies all hosted agents are responding with valid agent cards.
Designed to run after every publish/deployment.

Usage:
    python tests/smoke-test.py [base_url]
    python tests/smoke-test.py https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_BASE_URL = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io"
TIMEOUT_SECONDS = 15

# ── Agent endpoints to verify ─────────────────────────────────────────────

ENDPOINTS = [
    {
        "name": "Health Check",
        "path": "/health",
        "checks": ["has_field:status"],
    },
    {
        "name": "Root Agent Card (catalog)",
        "path": "/.well-known/agent-card.json",
        # Expect 3 agents once spec03 deploys; currently 2 (spec + echo)
        "checks": ["is_array", "has_v1_agent", "min_agents:2"],
    },
    {
        "name": "Echo Agent Card",
        "path": "/echo/.well-known/agent-card.json",
        "checks": ["has_name", "has_skills"],
    },
    {
        "name": "Spec Agent Card (v0.3)",
        "path": "/spec03/.well-known/agent-card.json",
        "checks": ["has_name", "has_skills", "protocol_version:0.3.0"],
    },
]


# ── Result tracking ───────────────────────────────────────────────────────

@dataclass
class CheckResult:
    endpoint: str
    check: str
    passed: bool
    detail: str = ""


# ── Check implementations ─────────────────────────────────────────────────

def check_is_array(data: object) -> CheckResult:
    ok = isinstance(data, list)
    return CheckResult("", "is_array", ok,
                       f"Got array with {len(data)} items" if ok else f"Expected array, got {type(data).__name__}")


def check_min_agents(data: object, count: int) -> CheckResult:
    if not isinstance(data, list):
        return CheckResult("", f"min_agents:{count}", False, "Not an array")
    ok = len(data) >= count
    return CheckResult("", f"min_agents:{count}", ok,
                       f"Found {len(data)} agent(s)" if ok else f"Expected >= {count}, found {len(data)}")


def check_has_v1_agent(data: object) -> CheckResult:
    """At least one agent in the catalog has supportedInterfaces with a protocolVersion."""
    if not isinstance(data, list):
        return CheckResult("", "has_v1_agent", False, "Not an array")
    for agent in data:
        if not isinstance(agent, dict):
            continue
        ifaces = agent.get("supportedInterfaces")
        if isinstance(ifaces, list) and len(ifaces) > 0:
            for iface in ifaces:
                if isinstance(iface, dict) and iface.get("protocolVersion"):
                    return CheckResult("", "has_v1_agent", True,
                                       f"v1.0 agent found: {agent.get('name', '?')}")
    return CheckResult("", "has_v1_agent", False, "No agent with supportedInterfaces + protocolVersion")


def check_has_name(data: object) -> CheckResult:
    if isinstance(data, list):
        # If array, check first item
        data = data[0] if data else {}
    ok = isinstance(data, dict) and bool(data.get("name"))
    name = data.get("name", "") if isinstance(data, dict) else ""
    return CheckResult("", "has_name", ok,
                       f"name: {name}" if ok else "Missing 'name' field")


def check_has_skills(data: object) -> CheckResult:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return CheckResult("", "has_skills", False, "Not a dict")
    skills = data.get("skills")
    ok = isinstance(skills, list) and len(skills) > 0
    return CheckResult("", "has_skills", ok,
                       f"{len(skills)} skill(s)" if ok else "Missing or empty 'skills'")


def check_protocol_version(data: object, expected: str) -> CheckResult:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return CheckResult("", f"protocol_version:{expected}", False, "Not a dict")
    pv = data.get("protocolVersion", "")
    ok = pv == expected
    return CheckResult("", f"protocol_version:{expected}", ok,
                       f"protocolVersion: {pv}" if ok else f"Expected '{expected}', got '{pv}'")


def check_has_field(data: object, field: str) -> CheckResult:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return CheckResult("", f"has_field:{field}", False, "Not a dict")
    ok = field in data and data[field] is not None
    return CheckResult("", f"has_field:{field}", ok,
                       f"{field}: {data.get(field)}" if ok else f"Missing '{field}' field")


def run_checks(data: object, checks: list[str]) -> list[CheckResult]:
    results = []
    for check in checks:
        if check == "is_array":
            results.append(check_is_array(data))
        elif check == "has_v1_agent":
            results.append(check_has_v1_agent(data))
        elif check.startswith("min_agents:"):
            count = int(check.split(":")[1])
            results.append(check_min_agents(data, count))
        elif check == "has_name":
            results.append(check_has_name(data))
        elif check == "has_skills":
            results.append(check_has_skills(data))
        elif check.startswith("protocol_version:"):
            expected = check.split(":", 1)[1]
            results.append(check_protocol_version(data, expected))
        elif check.startswith("has_field:"):
            field_name = check.split(":", 1)[1]
            results.append(check_has_field(data, field_name))
        else:
            results.append(CheckResult("", check, False, f"Unknown check: {check}"))
    return results


# ── Main ──────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> tuple[int, Optional[object], str]:
    """Fetch URL and parse JSON. Returns (status_code, parsed_data, error_message)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            return resp.status, data, ""
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, None, f"Connection error: {e.reason}"
    except json.JSONDecodeError as e:
        return 200, None, f"Invalid JSON: {e}"
    except Exception as e:
        return 0, None, str(e)


def main() -> int:
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL

    print(f"🔍 AgentBin Smoke Test")
    print(f"   Target: {base_url}")
    print(f"   Endpoints: {len(ENDPOINTS)}")
    print()

    all_results: list[CheckResult] = []
    failures = 0

    for ep in ENDPOINTS:
        url = f"{base_url}{ep['path']}"
        print(f"── {ep['name']} ──")
        print(f"   GET {ep['path']}")

        status, data, error = fetch_json(url)

        if error:
            print(f"   ❌ FAIL — {error}")
            all_results.append(CheckResult(ep["name"], "http_200", False, error))
            failures += 1
            print()
            continue

        # HTTP 200 check
        if status == 200:
            print(f"   ✅ HTTP {status}")
            all_results.append(CheckResult(ep["name"], "http_200", True, f"HTTP {status}"))
        else:
            print(f"   ❌ HTTP {status}")
            all_results.append(CheckResult(ep["name"], "http_200", False, f"HTTP {status}"))
            failures += 1
            print()
            continue

        # Run structural checks
        for result in run_checks(data, ep["checks"]):
            result.endpoint = ep["name"]
            all_results.append(result)
            icon = "✅" if result.passed else "❌"
            print(f"   {icon} {result.check}: {result.detail}")
            if not result.passed:
                failures += 1

        print()

    # ── Summary ───────────────────────────────────────────────────────
    total = len(all_results)
    passed = total - failures
    print("━" * 50)
    if failures == 0:
        print(f"✅ All {total} checks passed — agents are healthy!")
    else:
        print(f"❌ {failures}/{total} checks failed")
        for r in all_results:
            if not r.passed:
                print(f"   FAIL: [{r.endpoint}] {r.check} — {r.detail}")
    print()

    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
