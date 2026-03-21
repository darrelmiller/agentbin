# Legacy — History

## 2026-03-21 — Spec03 404 Investigation

- Investigated `/spec03/.well-known/agent-card.json` returning 404 on live deployment
- Verified source code is correct locally — route properly defined in `Program.cs`
- Root cause: Deployed Azure Container App is stale (predates spec03 addition)
- No CI/CD pipeline currently exists for automatic container deployment
- Immediate fix: Rebuild and redeploy Docker container from `origin/main`
- v0.3 interop tests and A2A Editor discovery currently unavailable on live endpoint
- **Finding:** This is an operational issue, not a code bug — deployment is behind source
- Stale deployment highlights need for post-deploy smoke testing (see Dashboard agent outcome)

## Learnings

- Always verify code locally before assuming bugs
- Deployment gaps are as critical as code bugs for user experience
- Post-deploy verification is essential for rapid iteration
