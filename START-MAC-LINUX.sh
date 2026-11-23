#!/usr/bin/env bash
# Clip Cut AI on a Mac or Linux laptop. Needs Python 3.10+ and ffmpeg (Mac: brew install ffmpeg; Linux: sudo apt install ffmpeg python3-pip).
cd "$(dirname "$0")"
if [ ! -f .installed ]; then
  python3 -m pip install -r requirements.txt || { echo "Install failed. Check the internet and try again."; exit 1; }
  touch .installed
fi
( sleep 8; (command -v open >/dev/null && open http://127.0.0.1:8765) || xdg-open http://127.0.0.1:8765 ) >/dev/null 2>&1 &
python3 -m studio.server
