#!/bin/bash
# Install the pocket survival computer on Raspberry Pi OS Lite (Bookworm or Trixie, 64-bit).
# Run once, with internet, as the normal user (not root):   bash deploy/install.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"

echo "== Packages"
sudo apt-get update
sudo apt-get install -y python3 python3-smbus2 python3-serial python3-lgpio python3-numpy python3-pip gpsd gpsd-clients \
    i2c-tools cage curl network-manager alsa-utils fake-hwclock
# Pimoroni's BME680 library is not packaged in Debian; install it system-wide for the app service.
# Optional: without it the weather tab falls back to a BME280 or says the sensor is missing.
sudo pip3 install --break-system-packages bme680 2>/dev/null || sudo pip3 install bme680 || \
  echo "!! Could not install the bme680 package; the BME680 sensor will not be used."
sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser

echo "== Enable I2C (radio, weather sensor, compass) and the serial port (GPS)"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_serial_hw 0     # UART on
sudo raspi-config nonint do_serial_cons 1   # no login shell on it

echo "== gpsd on the UART"
sudo tee /etc/default/gpsd >/dev/null <<CFG
START_DAEMON="true"
USBAUTO="true"
DEVICES="/dev/serial0"
GPSD_OPTIONS="-n"
CFG
sudo systemctl enable gpsd

echo "== Direct WiFi: let the app switch the hotspot on and off"
sudo tee /etc/polkit-1/rules.d/50-doomsday-network.rules >/dev/null <<RULE
polkit.addRule(function(action, subject) {
  if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.user === "$USER_NAME") {
    return polkit.Result.YES;
  }
});
RULE

echo "== Durability: protect the SD card and recover from hangs"
# logs in RAM instead of constantly writing to the card
sudo mkdir -p /etc/systemd/journald.conf.d /etc/systemd/system.conf.d
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=20M\n' | sudo tee /etc/systemd/journald.conf.d/doomsday.conf >/dev/null
# no swap file on the SD card
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true
# don't write access times on every file read
sudo sed -i -E '/[[:space:]]\/[[:space:]]/ { /noatime/! s/(ext4[[:space:]]+)([^[:space:]]+)/\1\2,noatime/ }' /etc/fstab
# repair the file system automatically after a power cut
CMDLINE=/boot/firmware/cmdline.txt; [ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
grep -q 'fsck.repair=yes' "$CMDLINE" || sudo sed -i 's/$/ fsck.repair=yes/' "$CMDLINE"
# hardware watchdog: reboot by itself if the system ever freezes
printf '[Manager]\nRuntimeWatchdogSec=15\n' | sudo tee /etc/systemd/system.conf.d/doomsday-watchdog.conf >/dev/null
# allow the app to shut down cleanly when the battery runs out
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff" | sudo tee /etc/sudoers.d/doomsday-poweroff >/dev/null
sudo chmod 440 /etc/sudoers.d/doomsday-poweroff
# no clock battery and maybe no GPS fix: let the app set the clock (tap the clock, or from your computer)
sudo tee /etc/sudoers.d/doomsday-clock >/dev/null <<SUDO
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/date -u -s *, /usr/sbin/fake-hwclock save, /usr/sbin/hwclock -w
SUDO
sudo chmod 440 /etc/sudoers.d/doomsday-clock

echo "== Weather fax / RTTY: USB sound stick access and the Si4732 SSB patch"
sudo usermod -aG audio "$USER_NAME"
mkdir -p "$APP_DIR/data"
if [ ! -f "$APP_DIR/data/ssb_patch.bin" ]; then
  python3 "$APP_DIR/tools/get_ssb_patch.py" "$APP_DIR/data/ssb_patch.bin" || \
    echo "   Could not download the SSB patch now. FM/AM/SW work; run tools/get_ssb_patch.py later for fax/RTTY."
fi

echo "== App service"
mkdir -p "$APP_DIR/data"
sudo tee /etc/systemd/system/doomsday.service >/dev/null <<UNIT
[Unit]
Description=Pocket survival computer
After=network.target gpsd.service

[Service]
User=$USER_NAME
ExecStart=/usr/bin/python3 $APP_DIR/app/server.py --data $APP_DIR/data
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now doomsday

echo "== Offline libraries: kiwix-serve for Wikipedia / WikiMed / Khan Academy (.zim files)"
# The official static build is the newest; the Debian package is the fallback.
ARCH=$(uname -m)   # aarch64 on 64-bit Pi OS, armv7l/armhf on 32-bit
case "$ARCH" in aarch64) KARCH=aarch64 ;; armv7l|armhf) KARCH=armv8 ;; *) KARCH="" ;; esac
if [ -n "$KARCH" ] && curl -fsSL -o /tmp/kiwix-tools.tar.gz \
     "https://download.kiwix.org/release/kiwix-tools/kiwix-tools_linux-$KARCH.tar.gz"; then
  tar -xzf /tmp/kiwix-tools.tar.gz -C /tmp
  sudo install -m 755 /tmp/kiwix-tools_linux-*/kiwix-serve /usr/local/bin/kiwix-serve
  rm -rf /tmp/kiwix-tools.tar.gz /tmp/kiwix-tools_linux-*
else
  sudo apt-get install -y kiwix-tools
fi
mkdir -p "$APP_DIR/data/zim" "$APP_DIR/data/videos"
sudo tee /etc/systemd/system/kiwix.service >/dev/null <<UNIT
[Unit]
Description=Offline libraries (kiwix-serve)
After=local-fs.target

[Service]
User=$USER_NAME
ExecStart=/bin/bash $APP_DIR/deploy/kiwix.sh
Restart=always
RestartSec=5
Nice=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now kiwix

if [ "${SCREEN:-waveshare35b}" = "waveshare35b" ]; then
  # Waveshare 3.5" RPi LCD (B); use SCREEN=hdmi for a normal monitor instead
  bash "$APP_DIR/deploy/screen.sh"
fi

echo "== Kiosk: auto-login on tty1 and show the app full screen"
sudo raspi-config nonint do_boot_behaviour B2   # console autologin
cp "$APP_DIR/deploy/kiosk.sh" "$HOME/kiosk.sh"
chmod +x "$HOME/kiosk.sh"
grep -q kiosk.sh "$HOME/.bash_profile" 2>/dev/null || \
  echo '[ "$(tty)" = "/dev/tty1" ] && exec ~/kiosk.sh' >> "$HOME/.bash_profile"

echo "== Airband: RTL-SDR stick (rtl_fm)"
sudo apt-get install -y rtl-sdr
# the TV-tuner driver grabs the stick otherwise
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf >/dev/null
sudo usermod -aG plugdev "$USER_NAME"

echo "== DS3231 clock chip: keeps the time while switched off (no internet or GPS needed)"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
grep -q '^dtoverlay=i2c-rtc' "$CFG" || echo 'dtoverlay=i2c-rtc,ds3231' | sudo tee -a "$CFG" >/dev/null
# After the first boot with internet or GPS time:  sudo hwclock -w   (the app also does this when you set the clock)

if [ "${NO_WIFI:-0}" = "1" ]; then
  echo "== NO_WIFI=1: switch WiFi and Bluetooth off at the next boot"
  # Saves power and frees the good UART for the GPS. Nothing in the app needs WiFi; it is only
  # used to refresh the forecast when available. To undo: delete these two lines from
  # config.txt on the SD card's boot partition.
  CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
  grep -q '^dtoverlay=disable-wifi' "$CFG" || echo 'dtoverlay=disable-wifi' | sudo tee -a "$CFG" >/dev/null
  grep -q '^dtoverlay=disable-bt' "$CFG" || echo 'dtoverlay=disable-bt' | sudo tee -a "$CFG" >/dev/null
  sudo systemctl disable hciuart 2>/dev/null || true
fi
sudo mkdir -p /boot/firmware/doomsday 2>/dev/null || true

echo
echo "Done. Copy your map database to $APP_DIR/data/nav.db (see README), then reboot."
