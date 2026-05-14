# Automation & Scheduling

This directory is intentionally empty. La Gran Crisis pipeline automation is managed via **Windows Task Scheduler** rather than GitHub Actions.

## Current Automation Strategy

### Why Windows Task Scheduler?
- **Local execution**: Pipeline runs on the author's machine with local filesystem access to `docs/`, `logs/`, and `raw/` directories.
- **Real-time control**: Allows manual intervention and debugging between scheduled runs.
- **Development-stage tooling**: Suitable for ongoing development and testing; can be migrated to GitHub Actions or a cloud scheduler later.

### Scheduled Tasks

Two Windows Task Scheduler tasks manage the pipeline:

| Task | Schedule | Command | Purpose |
|------|----------|---------|---------|
| **LGC-Intraday** | Hourly (08:00–04:59 ART) | `python src/main.py --intraday` | Accumulates breaking news articles from RSS feeds throughout the day. |
| **LGC-Close** | Daily @ 05:00 ART | `python src/main.py --close` | Publishes final digest, runs Judge evaluation, updates docs. |

Details: `scripts/setup_local_tasks.ps1`

### Future Consolidation

When the pipeline is promoted to production (cloud-hosted or GitHub Pages CI), consider:
- Migrating to GitHub Actions (`.github/workflows/*.yml`) for native integration.
- Using AWS Lambda, Google Cloud Functions, or a dedicated orchestrator for scheduling.
- Replacing Task Scheduler with cloud-native scheduling (AWS EventBridge, Google Cloud Scheduler, etc.).

---

**Last Updated**: 2026-04-24  
**Status**: Development (Task Scheduler)
