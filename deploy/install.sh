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
sudo rsync -a --delete --exclude .git "$SRC"/ /opt/upin/
sudo python3 -m venv /opt/upin/venv
sudo /opt/upin/venv/bin/pip install --upgrade pip
sudo /opt/upin/venv/bin/pip install -e "/opt/upin[box]"
[ -f /etc/upin/box.toml ] || sudo cp /opt/upin/deploy/box.example.toml /etc/upin/box.toml
sudo cp /opt/upin/deploy/upin-box.service /etc/systemd/system/
sudo chown -R upin:upin /opt/upin /var/log/upin
sudo systemctl daemon-reload

cat <<MSG
Installed. Next:
  1. Edit /etc/upin/box.toml (airframe limits, ports).
  2. Free the Pi's UART: sudo raspi-config -> Interface -> Serial:
     login shell over serial = No, serial hardware = Yes. Reboot.
  3. Test by hand, sending nothing:
       sudo -u upin /opt/upin/venv/bin/python -m upin.box.service \\
            --config /etc/upin/box.toml --no-send
  4. Only then: sudo systemctl enable --now upin-box
MSG
