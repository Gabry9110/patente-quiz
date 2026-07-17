# Stato del progetto — per riprendere il lavoro

## Cosa è stato fatto (completato e testato)

Tutta l'applicazione MVP è implementata e **verificata con smoke test HTTP** il 16/07/2026.

### Funzionalità completate
- ✅ **Stack**: Python 3.12 + FastAPI + SQLModel + Jinja2 + HTMX, Catppuccin Mocha/Mauve
- ✅ **Modelli DB**: User, Category, Question, Option, QuizSession, Answer
- ✅ **Auth**: tabella users, bcrypt (libreria `bcrypt` diretta, NON passlib), cookie di sessione itsdangerous, setup password al primo avvio per utente `gabry`
- ✅ **LLM**: client Ollama Cloud (`ollama` libreria ufficiale, host `https://ollama.com`, modello `deepseek-v4-flash`), system prompt elaborato, parser JSON robusto, self-check vs `riassunto-video.md`
- ✅ **Seed**: `app/seed.py` pre-genera 10 domande per 10 categorie (100 totali)
- ✅ **Route**: auth (login/logout/setup), dashboard, quiz (start/answer/next/end), questions (list + generate on-demand), review (sbagliate), stats (per categoria + storico)
- ✅ **Template**: base, login, dashboard, quiz_play, quiz_feedback (partial), quiz_end, questions_list, review, stats, error
- ✅ **CSS**: Catppuccin Mocha, accent Mauve, responsive mobile-first
- ✅ **Deploy**: `scripts/create_db.sh` (Postgres least-privilege), `deploy/patente-quiz.service`, `scripts/provision_lxc.sh` (LXC Proxmox ID 210, Debian 13, vmbr0, no Docker)

### Smoke test superati (20/07/2026, con SQLite locale)
Tutti i test in `scripts/smoke_test.py` passano:
- GET / (no auth) → 303 → /setup
- GET /setup → 200 "Primo avvio"
- POST /setup (crea gabry) → 303 / + cookie
- POST /setup di nuovo → 303 /login (già esiste)
- GET / (con cookie) → 200 "Ciao gabry"
- GET /stats → 200 "Statistiche"
- GET /review → 200 "Ripasso"
- GET /quiz/start?mode=mixed (no domande) → 303 /review?empty=1

## Come riprendere il lavoro

### 1. Clona il repo (se su GitHub) o usa la cartella locale
```bash
cd C:\Users\Gabriele\Documents\patente-quiz
```

### 2. Setup ambiente
```bash
python -m venv .venv
. .venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
cp .env.example .env
# genera SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"
# compila .env con DATABASE_URL, OLLAMA_API_KEY, SECRET_KEY
```

### 3. Smoke test locale (SQLite, senza Postgres né chiave Ollama vera)
```bash
. .venv\Scripts\Activate.ps1
$env:DATABASE_URL="sqlite:///./test_patente.db"
$env:SECRET_KEY="test-secret-key-for-smoke-test-only-32chars"
$env:OLLAMA_API_KEY="dummy"
# avvia il server in un terminale:
uvicorn app.main:app --port 8001 --host 127.0.0.1
# in un altro terminale, lancia il test:
python scripts\smoke_test.py
```
Deve stampare `ALL HTTP SMOKE TESTS PASSED`.

### 4. Deploy reale (quando sei pronto)
1. **Crea il DB Postgres** (puoi eseguire lo script dal tuo PC se raggiunge la VM):
   ```bash
   PGHOST=192.168.2.105 PGUSER=postgres PGPASSWORD=... bash scripts/create_db.sh
   ```
   Salva la connection string stampata. Su Arch/WSL installa `psql` con `sudo pacman -S postgresql`.

2. **Crea l'LXC Proxmox** (dall'host Proxmox):
   ```bash
   bash scripts/provision_lxc.sh
   ```

3. **Configura .env dentro l'LXC**:
   ```bash
   pct exec 210 -- bash -c 'cp /opt/patente-quiz/.env.example /opt/patente-quiz/.env && nano /opt/patente-quiz/.env'
   ```
   Compila DATABASE_URL, OLLAMA_API_KEY, SECRET_KEY.

4. **Avvia l'app**:
   ```bash
   pct exec 210 -- systemctl start patente-quiz
   pct exec 210 -- systemctl status patente-quiz
   ```

5. **Pre-popolale le domande**:
   ```bash
   pct exec 210 -- /opt/patente-quiz/.venv/bin/python -m app.seed
   ```

6. **Cloudflare Tunnel** → punta a `http://<LXC_IP>:8000`

7. **Primo avvio** nel browser → setup password per `gabry`.

## Cosa NON è ancora stato testato (punti da verificare)

Questi non sono coperti dallo smoke test e potrebbero avere bug residui:

1. **Generazione LLM reale**: `app/llm.py` chiama Ollama Cloud. Testare con una chiave API vera lanciando:
   ```bash
   python -m app.seed --no-selfcheck  # prima solo 1-2 categorie per non sprecare crediti
   ```
   Verificare che il JSON torni parsato correttamente e le domande finiscano nel DB.

2. **Self-check LLM**: il secondo prompt di verifica. Prova con:
   ```bash
   python -m app.seed   # con self-check attivo
   ```
   Controllare il campo `verified` e `verification_note` nelle domande create.

3. **Flusso quiz completo** (con domande vere nel DB):
   - GET /quiz/start?mode=category&slug=luci-fari → deve renderizzare la domanda
   - POST /quiz/answer → partial HTMX con feedback corretto/errato
   - GET /quiz/next → domanda successiva
   - GET /quiz/end → punteggio + riepilogo sbagliate

4. **Generazione on-demand**: tasto "+ Genera domanda" in dashboard/questions_list. Verifica che la nuova domanda appaia nel banco globale.

5. **Statistiche con dati**: dopo qualche sessione, /stats deve mostrare barre per categoria e sessioni recenti.

6. **Quiz mode=wrong**: richiede domande sbagliate nelle sessioni passate.

7. **Template quiz_end.html**: usa espressione inline `{{ 'var(--success)' if score == total else 'var(--accent)' }}` — verificare che Jinja2 la renda correttamente nel tag `style`.

8. **Deploy LXC senza Docker**: verificare che `provision_lxc.sh` su Proxmox crei correttamente il CT Debian 13, installi il venv, copi il service systemd e che `systemctl start patente-quiz` porti l'app in ascolto su `http://<LXC_IP>:8000`.

## Struttura del repo
```
patente-quiz/
├─ app/
│  ├─ main.py, config.py, db.py, models.py, auth.py, llm.py, seed.py
│  ├─ routes/ (auth, dashboard, quiz, questions, review)
│  └─ templates/ (base, login, dashboard, quiz_*, review, stats, error, partials/)
├─ data/ (lista-argomenti.md, riassunto-video.md)
├─ static/css/catppuccin-mocha.css
├─ scripts/ (create_db.sh, provision_lxc.sh, smoke_test.py)
├─ deploy/ (patente-quiz.service, Dockerfile, docker-compose.yml)
├─ requirements.txt, .env.example, .gitignore
├─ README.md, AGENTS.md, CONTINUA.md (questo file)
```

## Note tecniche
- **bcrypt**: usa la libreria `bcrypt` diretta (non passlib) perché passlib 1.7.4 ha un bug con bcrypt 4.x su Python 3.14. Password troncate a 72 byte.
- **DB driver**: `config.py` converte `postgresql://` → `postgresql+psycopg://` per usare psycopg3 (non psycopg2).
- **Jinja2**: NON usa operatore ternario `? :` (sintassi JS). Usa `{% if %}{% else %}{% endif %}`.
- **SQLAlchemy cast**: `review.py` usa `from sqlalchemy import Integer, cast` per `cast(Answer.is_correct, Integer)` (non `func.cast`).

## Per l'upload su GitHub
```bash
git remote add origin https://github.com/<tuo-username>/patente-quiz.git
git branch -M main
git push -u origin main
```
Il repo è già inizializzato con commit `init: patente-quiz MVP`.