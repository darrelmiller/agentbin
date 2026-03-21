# Squad Decisions

## Active Decisions

### Post-Deployment Smoke Testing (2026-03-21)
**Status:** Implemented | **Author:** Dashboard  

- Smoke test script at `tests/smoke-test.py` verifies all hosted agent endpoints
- Uses stdlib only (no pip install needed) — consistent with run-all.py patterns
- CI workflow at `.github/workflows/smoke-test.yml` supports:
  - `workflow_dispatch` for manual runs
  - `workflow_call` for chaining to future deploy workflows
  - Daily cron (8 AM UTC) as a health heartbeat
- Base URL parameterized (default: Azure Container Apps URL)
- **Endpoints tested:** /health, root catalog, /echo agent card, /spec03 v0.3 agent card

### Spec03 404 is a Deployment Gap (2026-03-21)
**Status:** Identified | **Author:** Legacy  

- Root cause: Deployed container predates spec03 addition — deployment is behind source code
- Source code is correct and works locally (`Program.cs` has proper route)
- **Fix:** Rebuild and redeploy Docker container from `origin/main`
- Impact: v0.3 interop tests and A2A Editor discovery currently unavailable
- No code changes needed — pure operational fix

### User Directive: Smoke Test After Every Publish (2026-03-21)
**Status:** Captured | **By:** Darrel (via Copilot)

- Context: spec03 agent broke in production without being caught by automated checks
- Directive: "We should be smoke testing agents after every publish"
- Implementation: See Post-Deployment Smoke Testing decision above

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
