### Extended Publish: Full docs/ Sync (2026-07-29)
**Status:** Implemented | **Author:** Dashboard

The `--publish` flag in `tests/run-all.py` now syncs ALL generated files to `docs/`, not just the aggregate dashboard and report-card. This eliminates the repeated problem of stale per-server dashboards, compliance reports, and index.html TCK stats after publishing.

**What changed:**
1. Per-server `dashboard-*.html` and `report-card-*.html` files are copied from `tests/` to `docs/`
2. TCK compliance reports are regenerated from `tests/TCKResults/{server}/` result JSONs into `docs/compliance-{server}.html` using `generate_compliance.py`'s `generate_compliance_html()` function
3. `docs/index.html` TCK stats blocks are auto-updated with current pass/fail/skip counts and color-coded percentages

**Design decisions:**
- `generate_compliance_html()` is imported lazily at runtime to avoid coupling
- TCK outcome counting uses the same grouping logic as `generate_compliance.py` (worst outcome across transports per test function)
- SDK version strings in index.html are preserved from existing HTML (not auto-detected)
- All steps fail gracefully with warnings if source files are missing

**Team impact:**
- Spec/server agents: After running TCK, results in `tests/TCKResults/{server}/` will automatically flow to docs/ on next publish
- All agents: `--publish` is now a single command that updates everything — no manual steps needed
