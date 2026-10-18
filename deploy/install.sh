#!/usr/bin/env bash
# Install the UPIN box on Raspberry Pi OS (64-bit, Bookworm or later).
# UNTESTED on a Pi. Read before running; run as a normal user with sudo.
#
#   git clone <repo> && cd upin && bash deploy/install.sh
#
# It does NOT enable the service: run it by hand first (see deploy/README.md).
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev git rsync

id upin >/dev/null 2>&1 || sudo useradd --system --create-home --groups dialout upin
sudo mkdir -p /opt/upin /etc/upin /var/log/upin
sudo rsync -a --delete --exclude .git --exclude venv --exclude '*.jsonl' --exclude frames \
     --exclude '__pycache__' "$SRC"/ /opt/upin/
sudo python3 -m venv /opt/upin/venv
sudo /opt/upin/venv/bin/pip install --upgrade pip
sudo /opt/upin/venv/bin/pip install -e "/opt/upin[box]"
[ -f /etc/upin/box.toml ] || sudo cp /opt/upin/deploy/box.example.toml /etc/upin/box.toml
sudo cp /opt/upin/deploy/upin-box.service /etc/systemd/system/
sudo chown -R upin:upin /opt/upin /var/log/upin
sudo systemctl daemon-reload

cat <<MSG
Installed. Next (docs/FIRST_FLIGHT.md):
  1. Edit /etc/upin/box.toml (airframe limits, ports).
  2. If the receiver sends only NMEA, enable UBX from the Pi:
       /opt/upin/venv/bin/python /opt/upin/tools/configure_receiver.py --port /dev/serial/by-id/... --target usb
  3. Preflight, every time:
       sudo -u upin /opt/upin/venv/bin/python /opt/upin/tools/preflight.py --config /etc/upin/box.toml
  4. Run by hand, sending nothing:
       sudo -u upin /opt/upin/venv/bin/python -m upin.box.service \\
            --config /etc/upin/box.toml --no-send
  5. Only then: sudo systemctl enable --now upin-box   (the unit runs with --no-send)
MSG
