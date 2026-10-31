#!/bin/bash
# Serves every .zim file (Wikipedia, WikiMed, Khan Academy, ...) to the app on 127.0.0.1:8081/kiwix.
# Looks in data/zim plus the zim folder on the SD card's boot partition and a USB stick.
# New or removed files are picked up within a minute, no restart needed.
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIRS=("$APP_DIR/data/zim" /boot/firmware/doomsday/zim /media/doomsday/zim)
KIWIX=$(command -v kiwix-serve || echo /usr/local/bin/kiwix-serve)
PID=""
LAST=""
trap '[ -n "$PID" ] && kill $PID; exit 0' TERM INT
while true; do
  FILES=()
  for d in "${DIRS[@]}"; do
    [ -d "$d" ] && while IFS= read -r -d '' f; do FILES+=("$f"); done < <(find "$d" -maxdepth 2 -name '*.zim' -print0 | sort -z)
  done
  NOW="${FILES[*]}"
  if [ "$NOW" != "$LAST" ] || { [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; }; then
    [ -n "$PID" ] && kill "$PID" 2>/dev/null && wait "$PID" 2>/dev/null
    PID=""
    LAST="$NOW"
    if [ ${#FILES[@]} -gt 0 ]; then
      echo "kiwix: serving ${#FILES[@]} file(s)"
      # 2 threads: enough for one screen plus a hotspot visitor, light on the Pi Zero's 512 MB
      "$KIWIX" --address=127.0.0.1 --port=8081 --urlRootLocation=/kiwix --threads=2 "${FILES[@]}" &
      PID=$!
    else
      echo "kiwix: no .zim files yet in ${DIRS[*]}"
    fi
  fi
  sleep 60 & wait $!
done
