@echo off
title Installing GTA Clipper
cd /d "%~dp0"

where python >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add Python to PATH". & pause & exit /b)
where ffmpeg >nul 2>nul || (echo Installing ffmpeg... & winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements & echo. & echo ffmpeg installed. Close this window and double-click this file again. & pause & exit /b)

echo Setting things up. The first time takes a few minutes...
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt || (echo Setup failed. Send a screenshot of this window. & pause & exit /b)
python -m pip install -q -U yt-dlp

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assets\make_shortcuts.ps1"
echo.
echo Done! GTA Clipper is now on your Desktop and in the Start menu.
echo Opening it now. You can close this window.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop.py"
timeout /t 5 >nul
