#!/usr/bin/env bash
# Provision a Proxmox LXC container (ID 210) running Debian 12 with Docker,
# then deploy patente-quiz via docker compose.
#
# Run this from the Proxmox HOST (where `pct` is available).
# The script:
#  1. Creates the LXC (2GB RAM, 8GB disk, vmbr0)
#  2. Starts it and installs Docker + Docker Compose
#  3. Copies the project into /opt/patente-quiz
#  4. Starts the app via docker compose
#
# After it finishes, point your Cloudflare Tunnel to http://<LXC_IP>:8000.

set -euo pipefail

CT_ID="${CT_ID:-210}"
CT_HOSTNAME="${CT_HOSTNAME:-patente-quiz}"
CT_MEMORY="${CT_MEMORY:-2048}"
CT_DISK="${CT_DISK:-8}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
DEBIAN_TEMPLATE="${DEBIAN_TEMPLATE:-debian-12-standard_12.7-1_amd64.tar.zst}"
# Path to local template cache; Proxmox fetches automatically if missing.
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
ROOTFS_STORAGE="${ROOTFS_STORAGE:-local-lvm}"

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo ">> Creating LXC ${CT_ID} (${CT_HOSTNAME})..."
if pct status "${CT_ID}" >/dev/null 2>&1; then
  echo "   LXC ${CT_ID} already exists. Skipping creation."
else
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

echo ">> Installing Docker inside the LXC..."
pct exec "${CT_ID}" -- bash -euxc '
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
  docker --version
'

echo ">> Getting LXC IP..."
LXC_IP="$(pct exec "${CT_ID}" -- ip -4 -o addr show eth0 | awk "{print \$4}" | cut -d/ -f1 | head -1)"
echo "   LXC IP: ${LXC_IP}"

echo ">> Copying project files into the LXC..."
pct push "${CT_ID}" "${SRC_DIR}/requirements.txt" /opt/patente-quiz/requirements.txt --mkdir
pct push "${CT_ID}" "${SRC_DIR}/.env.example" /opt/patente-quiz/.env.example
pct push "${CT_ID}" "${SRC_DIR}/Dockerfile" /opt/patente-quiz/Dockerfile 2>/dev/null || \
  pct push "${CT_ID}" "${SRC_DIR}/deploy/Dockerfile" /opt/patente-quiz/Dockerfile
pct push "${CT_ID}" "${SRC_DIR}/deploy/docker-compose.yml" /opt/patente-quiz/docker-compose.yml
pct push "${CT_ID}" "${SRC_DIR}/data/lista-argomenti.md" /opt/patente-quiz/data/lista-argomenti.md
pct push "${CT_ID}" "${SRC_DIR}/data/riassunto-video.md" /opt/patente-quiz/data/riassunto-video.md

# Push the app and static directories as tarballs (pct push handles single files only).
( cd "${SRC_DIR}" && tar -czf /tmp/patente-app.tar.gz app static )
pct push "${CT_ID}" /tmp/patente-app.tar.gz /tmp/patente-app.tar.gz
pct exec "${CT_ID}" -- bash -c 'tar -xzf /tmp/patente-app.tar.gz -C /opt/patente-quiz && rm /tmp/patente-app.tar.gz'
rm -f /tmp/patente-app.tar.gz

echo
echo "========================================"
echo " LXC PROVISIONED"
echo "========================================"
echo " Container:  ${CT_ID} (${CT_HOSTNAME})"
echo " IP:         ${LXC_IP}"
echo " App dir:    /opt/patente-quiz"
echo
echo " NEXT STEPS"
echo " 1. Create the Postgres DB (run scripts/create_db.sh on 192.168.2.105)."
echo " 2. Inside the LXC, edit /opt/patente-quiz/.env:"
echo "      pct exec ${CT_ID} -- bash -c 'cp /opt/patente-quiz/.env.example /opt/patente-quiz/.env && nano /opt/patente-quiz/.env'"
echo "    Set DATABASE_URL, OLLAMA_API_KEY, SECRET_KEY."
echo " 3. Start the app:"
echo "      pct exec ${CT_ID} -- docker compose -f /opt/patente-quiz/docker-compose.yml up -d --build"
echo " 4. Seed the question bank:"
echo "      pct exec ${CT_ID} -- docker exec patente-quiz python -m app.seed"
echo " 5. Point your Cloudflare Tunnel to http://${LXC_IP}:8000"
echo " 6. Open the public URL in your browser -> first-run setup for user 'gabry'."
echo