# GTA Clipper

Paste a GTA stream link, get ready-to-post 9:16 clips (YouTube Shorts / TikTok / Reels style) with the
facecam on top, gameplay below, word-by-word captions and a hook at the start.
Everything runs on your own PC. Nothing is uploaded anywhere, except the optional Claude API calls.

## What it does, in simple terms

1. You paste a link to a **finished** stream (YouTube, Twitch, Kick) or a video file on your PC.
2. The app looks for the exciting moments (replays, chat spikes, loud reactions).
3. It downloads only ~1 minute around each moment, not the whole stream.
4. It writes out what the streamer said (speech-to-text), picks the best 15-45 seconds, and renders a vertical clip.
5. You review the clips in a small web UI, edit the hook/title/timing if you want, and save them.

## How it works

```
 stream link / video file
          |
          v
 [1] open_stream()      yt-dlp reads title, channel, length (refuses if still live)
          |
          v
 [2] build_queue()      score every 5-second slice of the stream using cheap signals:
          |               - YouTube: "most replayed" heatmap, chat replay speed, top comments with timestamps
          |               - Twitch:  chat replay speed
          |               - Kick / files / thin signals: loudness of the audio (audio-only download)
          |             -> a ranked queue of moments, at least 45 s apart
          v
 [3] download_windows() download just ~1 min around the top 5 moments
          |
          v
 [4] asr.transcribe()   word-level timestamps with Parakeet (sherpa-onnx), runs locally
          |
          v
 [5] pick the clip      with a Claude key: Claude looks at frames + transcript, keeps or skips the moment,
          |               picks start/end, writes hook, title, caption, hashtags,
          |               removes game-character dialogue and fixes misheard words
          |             without a key: pick the loudest reaction near the moment (+ facecam movement),
          |               use ready-made hooks you can edit
          v
 [6] av_lag.measure_mouth()  checks lip sync (mouth movement vs audio) and shifts captions to match
          |
          v
 [7] render_clip.render()    ffmpeg + Pillow: 1080x1920, facecam on top, gameplay below,
          |                  yellow word-by-word captions, hook card for the first ~3 seconds
          v
      workspace/clips/*.mp4  (shown in the UI as they finish)
```

"Make 10 more" runs the same loop on the same stream and skips moments it already used.
If the queue runs low, it searches the stream again more closely before saying the stream is used up.

### The files

| File | What it does |
|---|---|
| `desktop.py` | Opens the app in its own window (pywebview). Picks a free port and starts the Flask server. |
| `app.py` | Flask server and API (`/api/...`). Runs a background worker that processes jobs one at a time. |
| `static/index.html` | The whole UI: paste link, progress, clip cards, edit dialog, facecam/gameplay box picker, settings. |
| `pipeline.py` | The main flow: open stream, find moments, download windows, plan clips, render, re-render, per-streamer layouts. |
| `signals.py` | Finds moments: 5-second scoring buckets from heatmap, chat, comments and loudness. |
| `asr.py` | Speech-to-text with word timestamps. Downloads the model once into `models/`. |
| `av_lag.py` | Measures audio/video lag by comparing mouth movement to speech loudness. |
| `render_clip.py` | Builds the final 9:16 video with ffmpeg, captions and hook card (Pillow). |
| `claude_ai.py` | Optional Claude API calls: judge a moment, suggest the facecam box, test the key. |
| `blocked_words.txt` | Words you never want in a clip. Moments containing them are skipped. |
| `Install on Mac.command`, `Install on Windows.bat`, `start.sh` | Installers / launcher. Set up a virtual env, install requirements, create the app icon. |
| `assets/` | App icons and the Windows shortcut script. |

### Main tools it uses

- **yt-dlp** to read stream info, chat, comments and download only the parts it needs
- **ffmpeg** to cut, crop, stack and encode video
- **sherpa-onnx + Parakeet** for local speech-to-text
- **Flask** and **pywebview** for the UI and the desktop window
- **Pillow / numpy** for captions, hook cards and the signal maths
- **Claude API** (optional) for smarter moment picking and writing hooks/titles

## Install it (one time)

The installer sets everything up and adds a **GTA Clipper** app icon. After that, you open it like any other app.
It opens in its own window, not in a browser tab.

### Mac
1. Install **Python 3.10 or newer** from python.org, and **Homebrew** from brew.sh.
2. Right-click **Install on Mac.command** and choose **Open** (then **Open** again if macOS asks).
3. Wait a few minutes. When it's done, **GTA Clipper** is in your Applications folder and opens by itself.
4. To keep it in the Dock: right-click its Dock icon > Options > Keep in Dock.

### Windows
1. Install **Python 3.10 or newer** from python.org. Tick **"Add Python to PATH"** during install.
2. Double-click **Install on Windows.bat**. If Windows shows "Windows protected your PC", click
   **More info** > **Run anyway**. If it installs ffmpeg, run it a second time when it asks.
3. When it's done, **GTA Clipper** is on your Desktop and in the Start menu, and it opens by itself.

**Important:** the app runs from this gta-clipper folder, so don't move or delete it after installing.
If you do move it, just run the installer again from the new place.

Closing the app window stops the app. If something goes wrong, the details are in `workspace/app.log`.

Linux: run `./start.sh` (opens in the browser).

## How to use it

1. Paste a **finished** stream link (YouTube, Twitch or Kick VOD), or the full path of a video file on your PC.
2. Pick how many clips and click **Find clips**.
3. The first time you clip a streamer, the app shows a frame from the stream. Drag one box over the
   **facecam** and one over the **gameplay**, then save. It remembers this for that streamer.
4. Clips appear as they finish. Save them to your Downloads folder, copy the title and hashtags, or click **Edit** to
   change the hook, title or start/end time and re-render.
5. Click **Make 10 more** to get the next batch from the same stream. It never repeats a moment.

The very first clip takes longer because the app downloads the speech model once (about 500 MB).

## Claude API key (optional)

Open **Settings** and paste a key from console.anthropic.com to turn on Claude. Then Claude:
- looks at each moment and skips the boring ones,
- removes game character dialogue from the captions and fixes misheard words,
- writes the hook, title and caption for every clip,
- finds the facecam box for you the first time.

Each clip costs a few cents of API usage. Without a key, the app still works: it picks moments by
replays, chat activity, comments and loud reactions, and uses ready-made hooks you can edit.

## How it finds moments

- **YouTube**: "Most replayed" data, chat replay speed, and top comments with timestamps.
- **Twitch**: chat replay.
- **Kick and video files**: loud reactions across the whole stream (audio only is downloaded for this).
If a stream has few signals, it also scans the audio for loud reactions.

It then downloads only about a minute around each moment, not the whole stream.

## Where things are saved

- Clips: `workspace/clips/` (the **Open clips folder** button opens it)
- Saved facecam boxes: `workspace/streamers.json`
- Your API key: `workspace/settings.json` (stays on your PC)
- Windows and downloads per stream: `workspace/streams/`. You can delete this folder for a stream
  once you're happy with the clips, but then you can't re-render them.

## Common problems

- **"This stream is still live"**: wait until the stream ends and use the VOD link.
- **403 errors on a stream that just ended**: YouTube is still processing very long streams. Try again in a few hours.
- **Downloads stopped working**: sites change often. Run the installer again to update the downloader.
- **Wrong facecam crop**: click **Redo facecam box**, then make the next batch.
- **Captions in the wrong place or out of sync**: the app checks lip sync automatically, but you can
  adjust the start/end time and re-render.

Only clip streams you have permission to use, and follow each platform's rules.

## Run it from source (developers)

```bash
git clone <this repo>
cd gta-clipper
./start.sh            # Mac / Linux: makes a .venv, installs requirements, runs app.py
```

Then open http://localhost:5000. `python desktop.py` opens the same app in its own window.
You need Python 3.10+ and ffmpeg on your PATH.
