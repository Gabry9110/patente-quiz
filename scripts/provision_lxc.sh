#!/usr/bin/env bash
# Provision a Proxmox LXC container (ID 210) running Debian 13 with a Python
# virtualenv and a systemd service. No Docker inside the container.
#
# Run this from the Proxmox HOST (where `pct` is available).
# The script:
#  1. Creates the LXC (2GB RAM, 8GB disk, vmbr0)
#  2. Starts it and installs Python + build deps
#  3. Creates a dedicated `patente-quiz` system user
#  4. Copies the project into /opt/patente-quiz
#  5. Creates a virtualenv and installs requirements
#  6. Installs and enables a systemd service
#  7. Leaves the service stopped until .env is configured
#
# After it finishes, point your Cloudflare Tunnel to http://<LXC_IP>:8000.

set -euo pipefail

CT_ID="${CT_ID:-210}"
CT_HOSTNAME="${CT_HOSTNAME:-patente-quiz}"
CT_MEMORY="${CT_MEMORY:-2048}"
CT_DISK="${CT_DISK:-8}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
# Adjust the exact template version if Proxmox offers a different Debian 13 image.
DEBIAN_TEMPLATE="${DEBIAN_TEMPLATE:-debian-13-standard_13.6-1_amd64.tar.zst}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
ROOTFS_STORAGE="${ROOTFS_STORAGE:-local-lvm}"
APP_USER="patente-quiz"
APP_DIR="/opt/patente-quiz"

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo ">> Creating LXC ${CT_ID} (${CT_HOSTNAME})..."
if pct status "${CT_ID}" >/dev/null 2>&1; then
  echo "   LXC ${CT_ID} already exists. Skipping creation."
else
  # Make sure the template is available in the Proxmox template storage.
  if ! pveam list "${TEMPLATE_STORAGE}" | grep -q "${DEBIAN_TEMPLATE}"; then
    echo ">> Downloading ${DEBIAN_TEMPLATE} to ${TEMPLATE_STORAGE}..."
    pveam download "${TEMPLATE_STORAGE}" "${DEBIAN_TEMPLATE}"
  fi

  pct create "${CT_ID}" "${TEMPLATE_STORAGE}:vztmpl/${DEBIAN_TEMPLATE}" \
    --arch amd64 \
    --hostname "${CT_HOSTNAME}" \
    --memory "${CT_MEMORY}" --swap 0 \
    --rootfs "${ROOTFS_STORAGE}:${CT_DISK}" \
    --net0 "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
    --features nesting=1 \
    --onboot 1 \
    --start 0
fi

echo ">> Starting LXC..."
pct start "${CT_ID}" || true
sleep 5

echo ">> Installing Python and build dependencies inside the LXC..."
pct exec "${CT_ID}" -- bash -euxc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    libpq-dev gcc curl ca-certificates
'

echo ">> Creating dedicated app user ${APP_USER}..."
pct exec "${CT_ID}" -- bash -euxc "
  id -u ${APP_USER} >/dev/null 2>&1 || \
    useradd --system --home-dir ${APP_DIR} --no-create-home ${APP_USER}
"

echo ">> Copying project files into the LXC..."
pct exec "${CT_ID}" -- bash -euxc "mkdir -p ${APP_DIR}"
pct push "${CT_ID}" "${SRC_DIR}/requirements.txt" "${APP_DIR}/requirements.txt"
pct push "${CT_ID}" "${SRC_DIR}/.env.example" "${APP_DIR}/.env.example"
pct push "${CT_ID}" "${SRC_DIR}/data/lista-argomenti.md" "${APP_DIR}/data/lista-argomenti.md"
pct push "${CT_ID}" "${SRC_DIR}/data/riassunto-video.md" "${APP_DIR}/data/riassunto-video.md"

# Push the app and static directories as tarballs (pct push handles single files only).
( cd "${SRC_DIR}" && tar -czf /tmp/patente-app.tar.gz app static )
pct push "${CT_ID}" /tmp/patente-app.tar.gz /tmp/patente-app.tar.gz
pct exec "${CT_ID}" -- bash -c "tar -xzf /tmp/patente-app.tar.gz -C ${APP_DIR} && rm -f /tmp/patente-app.tar.gz"
rm -f /tmp/patente-app.tar.gz

echo ">> Creating Python virtualenv and installing requirements..."
pct exec "${CT_ID}" -- bash -euxc "
  cd ${APP_DIR}
  python3 -m venv .venv
  .venv/bin/pip install --no-cache-dir -r requirements.txt
  chown -R ${APP_USER}:${APP_USER} ${APP_DIR}
"

echo ">> Installing systemd service..."
pct push "${CT_ID}" "${SRC_DIR}/deploy/patente-quiz.service" /etc/systemd/system/patente-quiz.service
pct exec "${CT_ID}" -- systemctl daemon-reload
pct exec "${CT_ID}" -- systemctl enable patente-quiz.service

echo ">> Getting LXC IP..."
LXC_IP="$(pct exec "${CT_ID}" -- ip -4 -o addr show eth0 | awk "{print \$4}" | cut -d/ -f1 | head -1)"
echo "   LXC IP: ${LXC_IP}"

echo
echo "========================================"
echo " LXC PROVISIONED"
echo "========================================"
echo " Container:  ${CT_ID} (${CT_HOSTNAME})"
echo " IP:         ${LXC_IP}"
echo " App dir:    ${APP_DIR}"
echo " App user:   ${APP_USER}"
echo
echo " NEXT STEPS"
echo " 1. Create the Postgres DB from your PC:"
echo "      PGHOST=192.168.2.105 PGUSER=postgres PGPASSWORD=<postgres-pw> bash scripts/create_db.sh"
echo " 2. Inside the LXC, edit ${APP_DIR}/.env:"
echo "      pct exec ${CT_ID} -- bash -c 'cp ${APP_DIR}/.env.example ${APP_DIR}/.env && nano ${APP_DIR}/.env'"
echo "    Set DATABASE_URL, OLLAMA_API_KEY, SECRET_KEY."
echo " 3. Start the app:"
echo "      pct exec ${CT_ID} -- systemctl start patente-quiz"
echo " 4. Seed the question bank:"
echo "      pct exec ${CT_ID} -- ${APP_DIR}/.venv/bin/python -m app.seed"
echo " 5. Point your Cloudflare Tunnel to http://${LXC_IP}:8000"
echo " 6. Open the public URL in your browser -> first-run setup for user 'gabry'."
echo
echo " Useful commands:"
echo "   pct exec ${CT_ID} -- systemctl status patente-quiz"
echo "   pct exec ${CT_ID} -- journalctl -u patente-quiz -f"
echo
