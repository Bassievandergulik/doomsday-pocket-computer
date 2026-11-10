#!/bin/bash
# Keeps colour inversion on for the Waveshare 3.5" LCD (B) (see deploy/screen.sh).
# The driver re-sends its start-up sequence whenever the screen is switched on again
# (boot, kiosk restart), which turns inversion off, so re-send it every few seconds.
# Sending it while it is already on changes nothing on screen.
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
while true; do
  for d in /sys/kernel/debug/dri/*; do
    if grep -qs ili9486 "$d/name" && [ -w "$d/command" ]; then
      echo 21 > "$d/command" 2>/dev/null
    fi
  done
  sleep 3
done
