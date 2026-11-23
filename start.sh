#!/usr/bin/env bash
# Mac / Linux. Needs Python 3.10+ and ffmpeg (brew install ffmpeg / sudo apt install ffmpeg)
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Please install ffmpeg first."; exit 1; }
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt && pip install -q -U yt-dlp
python app.py
