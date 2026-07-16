#!/usr/bin/env bash
# Create the patente_quiz database and a dedicated least-privilege app role
# on the existing Postgres VM (192.168.2.105).
#
# Best practices applied:
#  - dedicated LOGIN role with NO CREATEDB / NO CREATEROLE / NO SUPERUSER
#  - database owned by a privileged admin (NOT by the app role)
#  - REVOKE PUBLIC on database and schema
#  - GRANT CONNECT on DB, USAGE+CREATE on public schema to app role
#  - GRANT DML on all current + future tables, USAGE on all + future sequences
#  - strong random password (printed once)
#  - plaintext connection warning (no TLS configured in this homelab)
#
# Usage: run ON the Postgres host (or via psql over the LAN as a superuser):
#   PGHOST=127.0.0.1 PGUSER=postgres bash scripts/create_db.sh
#
# Set PGHOST/PGUSER/PGPORT env vars to target the VM if running remotely.

set -euo pipefail

DB_NAME="patente_quiz"
APP_ROLE="patente_quiz_app"
HOMELAB_HOST="${PGHOST:-192.168.2.105}"
PGADMIN="${PGUSER:-postgres}"

echo ">> Targeting Postgres at ${HOMELAB_HOST} as ${PGADMIN}"
echo ">> WARNING: this homelab Postgres has no TLS configured."
echo "   The app will connect with credentials in cleartext over the LAN."
echo "   Consider enabling TLS (ssl=prefer/prefer) on the Postgres server."
echo

# Generate a strong random password (32 chars, urlsafe).
APP_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
if [[ -z "${APP_PASSWORD}" ]]; then
  echo "! Could not generate a password. Install python3 or openssl." >&2
  exit 1
fi

PSQL=(psql -h "${HOMELAB_HOST}" -U "${PGADMIN}" -v ON_ERROR_STOP=1)

echo ">> Creating role ${APP_ROLE} (if not exists)..."
"${PSQL[@]}" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_ROLE}') THEN
    CREATE ROLE ${APP_ROLE}
      LOGIN
      NOCREATEDB
      NOCREATEROLE
      NOSUPERUSER
      NOREPLICATION
      CONNECTION LIMIT 20
      PASSWORD '${APP_PASSWORD}';
  ELSE
    ALTER ROLE ${APP_ROLE} PASSWORD '${APP_PASSWORD}';
  END IF;
END
\$\$;
SQL

echo ">> Creating database ${DB_NAME} (owned by ${PGADMIN})..."
"${PSQL[@]}" <<SQL
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${PGADMIN} ENCODING UTF8'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

echo ">> Locking down PUBLIC privileges..."
"${PSQL[@]}" -d "${DB_NAME}" <<SQL
REVOKE ALL ON DATABASE ${DB_NAME} FROM PUBLIC;
GRANT  CONNECT ON DATABASE ${DB_NAME} TO ${APP_ROLE};

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT  USAGE, CREATE ON SCHEMA public TO ${APP_ROLE};

-- DML on all existing tables in public
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${APP_ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ${APP_ROLE};

-- Inherit privileges on future tables/sequences created by the admin
ALTER DEFAULT PRIVILEGES FOR ROLE ${PGADMIN} IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_ROLE};
ALTER DEFAULT PRIVILEGES FOR ROLE ${PGADMIN} IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ${APP_ROLE};
SQL

echo
echo "========================================"
echo " DATABASE READY"
echo "========================================"
echo " Database:  ${DB_NAME}"
echo " Role:      ${APP_ROLE}"
echo " Password:  ${APP_PASSWORD}"
echo
echo " Connection string (put in .env as DATABASE_URL):"
echo "   postgresql://${APP_ROLE}:${APP_PASSWORD}@${HOMELAB_HOST}:5432/${DB_NAME}"
echo
echo " NOTE: store the password safely. It is NOT saved here."
echo "       Connection is cleartext (no TLS) — homelab use only."
echo