#!/usr/bin/env bash
# Deploy on Raspberry Pi 5 (Raspberry Pi OS Bookworm/Trixie 64-bit). Run:  bash install.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt

echo "[1/4] Installing packages"
sudo apt-get update
sudo apt-get install -y python3-numpy python3-scipy python3-flask alsa-utils device-tree-compiler

echo "[2/4] Building I2S overlay (4x INMP441)"
OV=/boot/firmware/overlays; [ -d "$OV" ] || OV=/boot/overlays
for v in i2s-4mic i2s-4mic-dmic i2s-4mic-spdif; do
  dtc -@ -H epapr -Wno-unit_address_vs_reg -I dts -O dtb -o /tmp/$v.dtbo "$DIR/boot/$v.dts" && sudo cp /tmp/$v.dtbo "$OV/"
done
grep -q '^dtparam=i2s=on' "$CFG" || echo 'dtparam=i2s=on' | sudo tee -a "$CFG" >/dev/null
grep -q '^dtoverlay=i2s-4mic' "$CFG" || echo 'dtoverlay=i2s-4mic' | sudo tee -a "$CFG" >/dev/null

echo "[3/4] Installing service"
sed "s#__INSTALL_DIR__#$DIR#g; s#__USER__#$USER#g" "$DIR/systemd/hearing-aid.service" | sudo tee /etc/systemd/system/hearing-aid.service >/dev/null
sudo systemctl daemon-reload; sudo systemctl enable hearing-aid.service
sudo usermod -aG audio "$USER" || true

echo "[4/4] Self-test (no hardware needed)"
python3 "$DIR/tools/selftest.py" || echo "WARNING: selftest failed"

cat <<MSG

Done. REBOOT now:  sudo reboot
After reboot:
  0) if 'arecord -l' shows no mic4 card:  bash $DIR/tools/overlay_try.sh   (tries 3 overlay variants, no reboot needed)
  1) python3 $DIR/tools/hw_check.py        # confirm 4 live channels (tap each mic)
  2) python3 $DIR/run.py --sim             # dashboard demo without mics
  3) sudo systemctl start hearing-aid      # real run;  http://<pi-ip>:8080
MSG
