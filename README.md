# Patente Quiz

Web app per esercitarsi con le domande di teoria della **fase 1 dell'esame pratico** della patente B.
Le domande sono generate da un LLM (Ollama Cloud, modello `deepseek-v4-flash`) e organizzate nelle 10 categorie richieste dall'istruttore.

## Stack
- Backend: Python 3.12 + FastAPI + SQLModel
- UI: Jinja2 + HTMX (server-rendered, ~14KB JS)
- DB: PostgreSQL (homelab)
- LLM: Ollama Cloud API (`ollama` Python client)
- Tema: Catppuccin Mocha, accent Mauve
- Deploy: LXC Proxmox Debian 13 + Python venv + systemd, Cloudflare Tunnel

## Funzionalità
- 10 categorie pre-seedate da `data/lista-argomenti.md`
- Pre-generazione di 10 domande per categoria (script `app/seed.py`)
- Generazione on-demand dal tasto "+ Genera domanda" (le domande finiscono nel banco globale su Postgres)
- Self-check automatico delle domande confrontando con `data/riassunto-video.md` (per le categorie coperte)
- Quiz per categoria, quiz misto, quiz solo-sbagliate
- Supporto a risposte multiple (una o più corrette)
- Feedback immediato con spiegazione e badge "verificata"/"da verificare"
- Ripasso domande sbagliate
- Statistiche per categoria + storico sessioni
- Auth singolo utente (`gabry`) con setup password al primo avvio
- Responsive (desktop + mobile)

## Setup rapido

### 1. Database Postgres
Puoi eseguire lo script dal tuo PC (WSL o desktop Arch Linux) se può raggiungere la VM Postgres sulla LAN:

```bash
PGHOST=192.168.2.105 PGUSER=postgres PGPASSWORD=... bash scripts/create_db.sh
```

Lo script crea il ruolo `patente_quiz_app` (least-privilege), il DB `patente_quiz`, revoca `PUBLIC`, imposta grant su schema/sequence/tabelle (anche future), stampa la connection string con password generata.

> **Requisiti**: lo script usa `psql` locale o, in alternativa, Docker. Su Arch Linux / WSL installa `psql` con `sudo pacman -S postgresql`.
>
> **Avviso**: il Postgres non ha TLS configurato, le credenziali viaggiano in chiaro sulla LAN. Per uso homelab è accettabile; in produzione abilitare `ssl=prefer`.

### 2. LXC Proxmox
Dal **host Proxmox**:

```bash
bash scripts/provision_lxc.sh
```

Crea l'LXC ID 210 (`patente-quiz`, Debian 13, 2GB RAM, 8GB disk, `vmbr0`, nesting abilitato, DHCP), crea un virtualenv Python e un systemd service, copia il progetto in `/opt/patente-quiz`. Non usa Docker.

### 3. Configura `.env` dentro l'LXC
```bash
pct exec 210 -- bash -c 'cp /opt/patente-quiz/.env.example /opt/patente-quiz/.env && nano /opt/patente-quiz/.env'
```

Compila:
- `DATABASE_URL` → dalla stringa stampata da `create_db.sh`
- `OLLAMA_API_KEY` → la tua chiave da https://ollama.com/settings/keys
- `SECRET_KEY` → genera con `python -c "import secrets; print(secrets.token_hex(32))"`
- `INITIAL_USERNAME=gabry` (già impostato di default)

### 4. Avvia l'app
```bash
pct exec 210 -- systemctl start patente-quiz
pct exec 210 -- systemctl status patente-quiz
```

### 5. Pre-popolare il banco domande
```bash
pct exec 210 -- /opt/patente-quiz/.venv/bin/python -m app.seed
```
Genera 100 domande (10 per categoria) con self-check. Usa `--no-selfcheck` per saltare la verifica e velocizzare:
```bash
pct exec 210 -- /opt/patente-quiz/.venv/bin/python -m app.seed --no-selfcheck
```

### 6. Cloudflare Tunnel
Punta il tunnel a `http://<LXC_IP>:8000` (IP stampato da `provision_lxc.sh`). Il tunnel gestisce TLS; l'app resta in HTTP interno.

### 7. Primo avvio
Apri l'URL pubblico → schermata "Primo avvio" → scegli password per `gabry` → entra.

## Sviluppo locale
```bash
python -m venv .venv && . .venv/Scripts/activate  # Windows
pip install -r requirements.txt
cp .env.example .env  # compila
uvicorn app.main:app --reload --port 8000
# in un altro terminale, per seedare:
python -m app.seed
```

## Struttura
```
app/
  main.py            FastAPI app + startup
  config.py          settings (env)
  db.py              engine SQLModel
  models.py          User, Category, Question, Option, QuizSession, Answer
  auth.py            bcrypt + session cookie itsdangerous
  llm.py             client Ollama, system prompt, JSON parser, self-check
  seed.py            pre-generazione domande
  routes/
    auth.py          login/logout/setup
    dashboard.py     /
    quiz.py          /quiz/* (start, answer, next, end)
    questions.py     /questions, /questions/generate
    review.py        /review, /stats
  templates/         Jinja2
static/css/          Catppuccin Mocha
data/                lista-argomenti.md, riassunto-video.md (read-only)
scripts/             create_db.sh, provision_lxc.sh
deploy/              patente-quiz.service, Dockerfile, docker-compose.yml
```

## Categorie (10)
1. Documenti necessari per la circolazione
2. Veicoli che si possono guidare con la patente B
3. Carta di Circolazione (DU)
4. Immatricolazione e Revisione
5. Luci in dotazione e uso dei fari
6. Dispositivi obbligatori a bordo
7. Limiti e normative per neopatentati
8. Controllo visivo degli pneumatici
9. Spie e comandi interni
10. Controllo dei livelli: olio motore e liquido refrigerante

Le categorie 5, 6, 8, 9, 10 (e la postazione di guida) sono coperte dal `riassunto-video.md` e usate come riferimento per la generazione e la verifica.
