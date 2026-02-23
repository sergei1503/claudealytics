# Claudealytics - Project Guide

## Branch Strategy

- **`dev`** — Active development branch. All new work happens here.
- **`main`** — Stable/release branch. Only receives merges from `dev` via PR.
- **NEVER push `dev` to origin.** The `dev` branch is local-only. Only `main` is pushed to the public remote.
- Local dev server (`claudealytics.localhost:1355`) always runs from `dev`.
- When starting a session, ensure you're on `dev`: `git checkout dev`

## Stack

- **Framework:** Streamlit
- **Language:** Python 3
- **Data:** Parses Claude Code JSONL conversation logs from `~/.claude/projects/`

## Dev Server

```bash
portless claudealytics bash -c 'python3 -m streamlit run src/claudealytics/dashboard/app.py --server.headless true --server.port $PORT'
```

URL: http://claudealytics.localhost:1355

## Project Structure

- `src/claudealytics/dashboard/layouts/` — Streamlit tab layouts (one file per tab)
- `src/claudealytics/analytics/parsers/` — Data extraction from JSONL files
- `src/claudealytics/analytics/aggregators/` — Domain-specific aggregation logic
- `src/claudealytics/dashboard/app.py` — Main Streamlit app entry point
- `src/claudealytics/models/schemas.py` — Data models
