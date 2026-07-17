# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`patente-quiz` is a FastAPI web app for practicing Italian driving-license (patente B) theory questions for the practical exam phase. It is server-rendered with Jinja2 + HTMX, uses SQLModel with PostgreSQL, and generates questions via the Ollama Cloud API (`deepseek-v4-flash`). Auth is single-user (`gabry`) with a first-run password setup flow.

## Common commands

### Local development

```bash
python -m venv .venv && . .venv/Scripts/activate  # on Windows; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Smoke test without Postgres or a real LLM key

```bash
. .venv/Scripts/Activate.ps1   # Windows
$env:DATABASE_URL="sqlite:///./test_patente.db"
$env:SECRET_KEY="test-secret-key-for-smoke-test-only-32chars"
$env:OLLAMA_API_KEY="dummy"
# in one terminal
uvicorn app.main:app --port 8001 --host 127.0.0.1
# in another terminal
python scripts/smoke_test.py
```

### Seed the question bank

```bash
python -m app.seed                 # generate 100 questions (10 per category) with LLM self-check
python -m app.seed --no-selfcheck  # faster, skips verification
```

On the LXC use the provisioned venv:

```bash
pct exec 210 -- /opt/patente-quiz/.venv/bin/python -m app.seed
```

### Production deploy (homelab)

1. Create the Postgres role/database from any PC that can reach the Postgres host:
   ```bash
   PGHOST=192.168.2.105 PGUSER=postgres PGPASSWORD=... bash scripts/create_db.sh
   ```
   On Arch Linux / WSL install `psql` with `sudo pacman -S postgresql`.
2. Provision the LXC container from Proxmox:
   ```bash
   bash scripts/provision_lxc.sh
   ```
3. Configure `.env` inside the LXC:
   ```bash
   pct exec 210 -- bash -c 'cp /opt/patente-quiz/.env.example /opt/patente-quiz/.env && nano /opt/patente-quiz/.env'
   ```
4. Start the app via systemd:
   ```bash
   pct exec 210 -- systemctl start patente-quiz
   pct exec 210 -- systemctl status patente-quiz
   ```
5. Pre-populate questions (see command above).
6. Point a Cloudflare Tunnel at `http://<LXC_IP>:8000` (the LXC IP is printed by `provision_lxc.sh`).

### First run

Open the public URL. If the `users` table is empty, the app redirects to `/setup` to set the password for the single configured user (`INITIAL_USERNAME`, default `gabry`).

## High-level architecture

### Server-rendered HTMX app

There is no frontend framework or client-side routing. `app/main.py` mounts `static/` and configures Jinja2 templates under `app/templates/`. HTMX is loaded via CDN in `base.html`, and interactive elements rely on `hx-post`, `hx-get`, and `hx-target`. Partial responses live in `app/templates/partials/`.

### Auth

Single-user flow: `app/auth.py` uses `bcrypt` directly (not passlib) and signs session cookies with `itsdangerous.URLSafeTimedSerializer`. `get_current_user` raises 401 for API/partial calls; `require_user_redirect` returns a 303 redirect for browser page routes. `app/routes/auth.py` handles `/setup`, `/login`, and `/logout`. On first run `needs_initial_setup()` is true and the dashboard redirects to `/setup`.

### Database and models

`app/models.py` defines `User`, `Category`, `Question`, `Option`, `QuizSession`, and `Answer`. Relationships are SQLModel relationships; `Answer.selected_option_ids` is stored as JSON. `app/db.py` creates a SQLModel engine and `init_db()` calls `SQLModel.metadata.create_all()` on startup. There is no migration tool (Alembic was intentionally omitted for this MVP); model changes take effect by recreating tables or calling `init_db()` against an empty DB.

`app/config.py` normalizes `postgresql://` and `postgresql+psycopg2://` URLs to `postgresql+psycopg://` so the psycopg3 driver is used. It also exposes `project_root` so code can reach `data/riassunto-video.md` reliably inside the LXC.

### LLM pipeline

All LLM calls route through `app/llm.py`:

1. `generate_questions()` sends a system prompt to Ollama Cloud and extracts a JSON array of questions. Each item must have `question`, `explanation`, and `options` (each option has `text` and `is_correct`). The response is cleaned and validated.
2. `self_check()` runs a second LLM pass to verify the generated question against the category reference material.
3. `reference_for_category()` maps category slugs to `###` sections of `data/riassunto-video.md` via `CATEGORY_REFERENCE_MAP`. Categories without a mapping get no reference text.

The API key never reaches the browser; it is read server-side from `OLLAMA_API_KEY`.

### Question sources

Questions can enter the database from two paths:

- `app/seed.py`: pre-generates `QUESTIONS_PER_CATEGORY` (10) questions for each of the 10 categories on first install. It is idempotent and skips categories that already have enough questions.
- `app/routes/questions.py`: the "+ Genera domanda" button calls `POST /questions/generate?category=<slug>&n=<1-5>` and returns an HTMX partial. Generated questions are stored with `source="ondemand"` in the global bank.

### Quiz flow

`app/routes/quiz.py` implements three modes: `category`, `mixed`, and `wrong`.

- `GET /quiz/start?mode=<mode>&slug=<slug>` creates a `QuizSession` and renders the first question.
- `POST /quiz/answer` records an `Answer` and returns `partials/quiz_feedback.html`.
- `GET /quiz/next` picks the next unanswered question (for `category` it stays within the category; for `wrong` it draws from questions answered incorrectly at least once and never later answered correctly). When no more questions remain it redirects to `/quiz/end?session_id=...`.
- `GET /quiz/end` finalizes the session and shows the score and review of wrong answers.

The quiz does not pre-lock a set of question IDs at start; each `/next` selects a fresh random question matching the mode, which means the same question can theoretically appear in one session if not yet answered.

### Review and stats

`app/routes/review.py`: `/review` shows questions answered wrong at least once and never correctly. `/stats` aggregates total answers/correct answers, per-category percentages, and recent sessions.

## Important conventions and caveats

- **No migrations**: schema is created automatically at startup. After model changes, drop/recreate the DB or target an empty one.
- **bcrypt passwords**: `app/auth.py` uses the `bcrypt` library directly and truncates passwords to 72 bytes before hashing.
- **Session cookie**: `secure=False` because TLS is terminated at Cloudflare Tunnel. If the origin receives HTTPS directly, set it to `True`.
- **SQLite smoke tests only**: the app starts with `sqlite:///`, but real LLM generation requires a valid `OLLAMA_API_KEY`.
- **Jinja2 syntax**: use `{% if %}{% else %}{% endif %}`, not JS-style ternary operators.
- **Reference map**: when adding categories, update `app/llm.py::CATEGORY_REFERENCE_MAP` if the new category has relevant material in `data/riassunto-video.md`.
