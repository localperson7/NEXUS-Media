# Contributing to NEXUS Media

Thank you for your interest in contributing to **NEXUS Media**.

## Guiding Principles

1. **Responsible Media Processing Only**: Pull requests that add DRM circumvention, login/cookie harvesting, private-account scraping, paywall bypass, or restriction evasion will not be accepted.
2. **Security by Default**: All URL inputs, redirects, and stream URLs extracted by external tools must pass through `backend/app/security.py`. Subprocess calls must always use argument arrays (`create_subprocess_exec`) with zero shell interpolation.
3. **Honest Metadata & Progress**: Never fabricate video resolutions that the source does not provide, and never invent progress percentages when total size or duration is unknown.
4. **Clean, Restrained UI**: Follow the existing graphite neutral dark/light design tokens in `frontend/src/styles/index.css` (4px spacing scale, tabular numerals, accessible focus states, zero decorative gradients or emoji navigation).

## Language Conventions

- **Code, comments, APIs, tests, and Git commits**: English.
- **User-facing application copy**: Russian (primary interface language for `v0.1.0-beta`).

## Local Development Setup

### Backend

```bash
cd backend
uv venv .venv
uv pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Required Checks Before Opening a PR

1. **Frontend unit tests and TypeScript production build**:
   ```bash
   cd frontend
   npm run test
   npm run build
   ```
2. **Backend test suite** (run after `frontend` build so unified server tests verify `frontend/dist`):
   ```bash
   cd backend
   .venv/bin/pytest -v
   ```
3. **No personal or runtime data in commits**: Never commit `.env`, SQLite `.db` files, `tmp_jobs/`, logs, or local absolute paths.

## Pull Request Process

- Keep pull requests focused on a single feature, provider, or bug fix.
- Add regression tests for every bug fix, security boundary, or database migration.
- Update `CHANGELOG.md` and `README.md` if user-visible behavior or supported sources change.
