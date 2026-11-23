#!/usr/bin/env bash
# Double-click to install GTA Clipper as a Mac app (in your Applications folder)
cd "$(dirname "$0")"
APPDIR="$(pwd)"
echo "Installing GTA Clipper..."
if ! command -v python3 >/dev/null; then echo "Python 3 is missing. Install it from python.org, then double-click this file again."; read -n1; exit 1; fi
if ! command -v ffmpeg >/dev/null; then
  if command -v brew >/dev/null; then echo "Installing ffmpeg..."; brew install ffmpeg
  else echo "ffmpeg is missing. Install Homebrew from brew.sh, then double-click this file again."; read -n1; exit 1; fi
fi
echo "Setting things up. The first time takes a few minutes..."
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt || { echo "Setup failed. Send a screenshot of this window."; read -n1; exit 1; }
pip install -q -U yt-dlp

# Build the app (it's just a folder with a launcher, an icon and some info)
APP="$HOME/Applications/GTA Clipper.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/icon.icns "$APP/Contents/Resources/icon.icns"
FFDIR="$(dirname "$(command -v ffmpeg)")"
cat > "$APP/Contents/MacOS/GTA Clipper" << EOF
#!/bin/bash
# Apps opened from the Dock don't see Homebrew's folder, so add it
export PATH="$FFDIR:/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$APPDIR"
exec "$APPDIR/.venv/bin/python" "$APPDIR/desktop.py"
EOF
chmod +x "$APP/Contents/MacOS/GTA Clipper"
cat > "$APP/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>GTA Clipper</string>
  <key>CFBundleDisplayName</key><string>GTA Clipper</string>
  <key>CFBundleIdentifier</key><string>local.gtaclipper.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>GTA Clipper</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
touch "$APP"
echo
echo "Done! GTA Clipper is in your Applications folder."
echo "Tip: right-click its icon in the Dock > Options > Keep in Dock."
echo "Don't move or delete this gta-clipper folder: the app runs from here."
open -R "$APP"
open "$APP"
