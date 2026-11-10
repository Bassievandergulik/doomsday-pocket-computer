#!/bin/bash
# Sends Waveshare's own panel settings for the 3.5" LCD (B) (see deploy/screen.sh).
# The kernel ili9486 driver's start-up sequence is written for the (A) panel: on the (B)
# its power/VCOM and gamma values make the picture washed-out grey with dark and light
# swapped. These are the values from Waveshare's waveshare35b-v2 overlay (colour inversion,
# power control, VCOM, frame rate, gamma), sent through the driver's debug interface.
# The driver sends its own values again when the screen is switched on (boot, kiosk
# restart), so repeat every few seconds; re-sending the same values changes nothing on screen.
SEQ=("21" "3a 55" "c2 33" "c5 00 1e 80" "b1 b0"
     "e0 00 13 18 04 0f 06 3a 56 4d 03 0a 06 30 3e 0f"
     "e1 00 13 18 01 11 06 38 34 4d 06 0d 0b 31 37 0f")
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
while true; do
  for d in /sys/kernel/debug/dri/*; do
    if grep -qs ili9486 "$d/name" && [ -w "$d/command" ]; then
      for x in "${SEQ[@]}"; do echo "$x" > "$d/command" 2>/dev/null; done
    fi
  done
  sleep 3
done
