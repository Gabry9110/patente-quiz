# AGENTS.md — patente-quiz

## Project
Python 3.12 + FastAPI + SQLModel + Jinja2/HTMX. Postgres backend.
LLM: Ollama Cloud (`ollama` package, model `deepseek-v4-flash`).
Deploy: Proxmox LXC Debian 13 + Python venv + systemd (no Docker in the container).

## Common commands

### Run dev server
```bash
uvicorn app.main:app --reload --port 8000
```

### Install deps
```bash
pip install -r requirements.txt
```

Inside the LXC, the provision script creates `/opt/patente-quiz/.venv` and installs requirements there.

### Lint / typecheck
No linter configured yet (single-contributor project, 2-week scope).
If adding one, use `ruff check app` and `mypy app`.

### Seed the question bank
```bash
python -m app.seed                # with self-check
python -m app.seed --no-selfcheck # faster, no verification
```

On the LXC use the venv Python:
```bash
pct exec 210 -- /opt/patente-quiz/.venv/bin/python -m app.seed
```

### Database
Schema is created automatically on app startup via `SQLModel.metadata.create_all`.
No migration tool (Alembic) for this 2-week MVP — recreate by dropping/recreating tables
or running `init_db()` after model changes.

### Tests
No test suite yet. To smoke-test locally:
1. `cp .env.example .env` and fill `DATABASE_URL`, `OLLAMA_API_KEY`, `SECRET_KEY`.
2. Start Postgres (or use the homelab one).
3. `python -m app.seed --no-selfcheck` to populate.
4. `uvicorn app.main:app --reload` and browse http://127.0.0.1:8000.

## Deploy (LXC)

1. Create the Postgres DB from any PC that can reach it:
   ```bash
   PGHOST=192.168.2.105 PGUSER=postgres PGPASSWORD=... bash scripts/create_db.sh
   ```
2. Provision the LXC from the Proxmox host:
   ```bash
   bash scripts/provision_lxc.sh
   ```
3. Configure `.env` inside the LXC and start the systemd service:
   ```bash
   pct exec 210 -- bash -c 'cp /opt/patente-quiz/.env.example /opt/patente-quiz/.env && nano /opt/patente-quiz/.env'
   pct exec 210 -- systemctl start patente-quiz
   ```

The container runs Debian 13 without Docker; the app is served by uvicorn inside a venv via `deploy/patente-quiz.service`.

## Conventions
- No JS framework; HTMX only (loaded via CDN in `base.html`).
- All LLM calls go through `app/llm.py` (backend only — never expose the API key client-side).
- Templates extend `base.html`; HTMX partials live in `templates/partials/`.
- CSS is a single hand-written file: `static/css/catppuccin-mocha.css` (Catppuccin Mocha, Mauve accent).
- Auth: single user created on first run via `/setup`. Session cookie signed with `SECRET_KEY`.
- Models in `app/models.py`; add new tables there and restart the app to auto-create.
- Routes are split under `app/routes/` and mounted in `app/main.py`.

## Files of note
- `data/lista-argomenti.md` — read-only source for categories.
- `data/riassunto-video.md` — read-only reference for LLM generation + self-check.
- `app/llm.py` `CATEGORY_REFERENCE_MAP` — maps category slugs to sections of the riassunto.
- `deploy/patente-quiz.service` — systemd unit for the LXC deployment.