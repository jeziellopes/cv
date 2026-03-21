# cv

Resume generator — edit `cv.json`, run one command, get a PDF.

## Stack

- Runtime: Python 3.12
- Framework: Typer (CLI)
- Database: {e.g., PostgreSQL} _(if applicable)_
- Cache: {e.g., Redis} _(if applicable)_
- Queue: {e.g., BullMQ} _(if applicable)_

## Commands

- Install: `pip install -r requirements.txt`
- Dev: `python main.py`
- Test: `pytest`
- Test single: `pytest -k <test_name>`
- Lint: `ruff check .`
- Build: `python -m build`

## Architecture

{Brief description of the high-level architecture and data flow.}

- `{src-dir}/` — {description}
- `{src-dir}/` — {description}

## Key Patterns

- {Pattern 1 — e.g., "Repository pattern for all database access"}
- {Pattern 2 — e.g., "Errors wrapped with context at every boundary"}

## Observability

- Logging: {library + format — e.g., "slog, structured JSON" or "pino, structured JSON with correlation IDs"}
- Metrics: {library or service — e.g., "Prometheus"}
- Tracing: {library or service — e.g., "OpenTelemetry"}

## Deployment

- Environment: {devops-platform}
- CI/CD: {ci-cd-platform}
- Secrets: {how secrets are managed — e.g., "env vars, never committed"}

## Conventions

- {Only things that differ from framework defaults}
- {Add project-specific patterns here}

## Secrets

- Manager: none (.env only)
- Load locally: `source .env`
- See `docs/secrets.md` for setup instructions

## Specs

- Feature specs live in `specs/` with acceptance criteria
- Use `/spec` to generate, `/red` → `/green` → `/refactor` for TDD workflow
