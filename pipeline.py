"""The clipping pipeline: stream link (or video file) -> queue of moments -> rendered 9:16 clips.
Follows the steps of the gta-clipping skill. Everything runs on this PC."""
import json, os, re, sys, glob, time, shutil, hashlib, subprocess, threading, traceback
from pathlib import Path

import numpy as np

import signals as sig
import asr
import av_lag
import render_clip
import claude_ai

HERE = Path(__file__).resolve().parent
WS = HERE / "workspace"
STREAMS = WS / "streams"
CLIPS = WS / "clips"
for d in (WS, STREAMS, CLIPS):
    d.mkdir(exist_ok=True)
SETTINGS = WS / "settings.json"
LAYOUTS = WS / "streamers.json"
LOCK = threading.RLock()

FACE_H = 740
SWEARS = re.compile(r"(fuck|shit|bitch|asshole|cunt|pussy|dick|bastard|motherf)", re.I)


# ---------------------------------------------------------------- small helpers
def jload(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def jsave(p, data):
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))
    os.replace(tmp, p)


def settings():
    return jload(SETTINGS, {"api_key": "", "model": "claude-sonnet-5-5"})


def ai_on():
    return bool(settings().get("api_key"))


def slug(s, n=40):
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:n] or "clip"


def hms(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def ytdlp(*args, cwd=None, check=True):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", *args]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "yt-dlp failed")
    return r


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                        "-of", "json", str(path)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    wh = next(((s["width"], s["height"]) for s in j.get("streams", []) if s.get("width")), (0, 0))
    return float(j.get("format", {}).get("duration", 0) or 0), wh


def censor(word):
    return SWEARS.sub(lambda m: m.group(0)[0].upper() + "*" * (len(m.group(0)) - 1), word)


def blocked_words():
    p = HERE / "blocked_words.txt"
    if not p.exists():
        return []
    return [l.strip().lower() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


# ---------------------------------------------------------------- progress (shown in the UI)
PROGRESS = {"busy": False, "stream": None, "step": "", "log": []}


def log(msg):
    with LOCK:
        PROGRESS["log"] = (PROGRESS["log"] + [time.strftime("%H:%M:%S ") + msg])[-200:]
    print(msg, flush=True)


def step(text):
    PROGRESS["step"] = text
    log(text)


# ---------------------------------------------------------------- streams
def stream_dir(sid):
    d = STREAMS / sid
    d.mkdir(exist_ok=True)
    return d


def meta(sid):
    if not re.fullmatch(r"[\w.-]+", sid or ""):
        return None  # a link or file path, not a stream id
    return jload(STREAMS / sid / "meta.json", None)


def save_meta(m):
    with LOCK:
        jsave(stream_dir(m["id"]) / "meta.json", m)


def queue(sid):
    return jload(stream_dir(sid) / "clip_queue.json", [])


def save_queue(sid, q):
    with LOCK:
        jsave(stream_dir(sid) / "clip_queue.json", q)


def all_streams():
    out = []
    for p in sorted(STREAMS.glob("*/meta.json"), key=os.path.getmtime, reverse=True):
        m = jload(p, None)
        if m:
            q = queue(m["id"])
            m["left"] = sum(1 for e in q if e["status"] == "new")
            out.append(m)
    return out


def source_kind(url):
    u = url.lower()
    if os.path.exists(url):
        return "file"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitch.tv" in u:
        return "twitch"
    if "kick.com" in u:
        return "kick"
    return "other"


def open_stream(url):
    """Get title, channel and length. Returns stream meta (creates it the first time)."""
    kind = source_kind(url)
    if kind == "file":
        dur, _ = probe(url)
        if not dur:
            raise RuntimeError("Could not read that video file. Check the path.")
        st = os.stat(url)
        sid = "file-" + hashlib.md5(f"{url}{st.st_size}".encode()).hexdigest()[:10]
        if meta(sid):
            return meta(sid)
        name = Path(url).stem
        m = {"id": sid, "url": url, "kind": kind, "title": name, "channel": name.split("_")[0][:30] or "Streamer",
             "duration": dur, "link": "", "clips": [], "next_n": 1, "used_up": False, "created": time.time()}
        save_meta(m)
        return m
    step("Reading stream info")
    info = json.loads(ytdlp("-J", "--no-playlist", "--", url).stdout)
    if info.get("is_live") or info.get("live_status") == "is_live":
        raise RuntimeError("This stream is still live. Wait until it ends, then paste the VOD link.")
    sid = slug(f"{info.get('extractor_key', kind)}-{info['id']}", 80)
    if meta(sid):
        return meta(sid)
    m = {"id": sid, "url": url, "kind": kind, "title": info.get("title") or info["id"],
         "channel": info.get("channel") or info.get("uploader") or "Streamer",
         "duration": float(info.get("duration") or 0), "link": info.get("webpage_url") or url,
         "clips": [], "next_n": 1, "used_up": False, "created": time.time()}
    if not m["duration"]:
        raise RuntimeError("Could not get the stream length. Is it a finished VOD?")
    jsave(stream_dir(sid) / "heat.json", info.get("heatmap") or [])
    save_meta(m)
    return m


# ---------------------------------------------------------------- step 2: find moments
def build_queue(m, gap=45, exclude=()):
    d = stream_dir(m["id"])
    sc = sig.Scorer(m["duration"])
    found = []
    if m["kind"] == "youtube":
        n = sc.heatmap(jload(d / "heat.json", []))
        found.append(f"replay data {'yes' if n else 'not available'}")
        if not (d / "chat.live_chat.json").exists():
            step("Reading chat replay")
            ytdlp("--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", "chat", "--", m["url"], cwd=d, check=False)
        cf = d / "chat.live_chat.json"
        n = sc.chat(sig.parse_youtube_chat(cf)) if cf.exists() else 0
        found.append(f"{n} chat messages")
        if not (d / "comments.info.json").exists():
            step("Reading top comments")
            ytdlp("--skip-download", "--write-comments", "--write-info-json", "--extractor-args",
                  "youtube:comment_sort=top;max_comments=1500,1500,0,0", "-o", "comments", "--", m["url"], cwd=d, check=False)
        n = sc.comments(jload(d / "comments.info.json", {}).get("comments") or [])
        found.append(f"{n} timestamped comments")
    elif m["kind"] == "twitch":
        if not glob.glob(str(d / "chat.*.json")):
            step("Reading chat replay")
            ytdlp("--skip-download", "--write-subs", "--sub-langs", "rechat", "-o", "chat", "--", m["url"], cwd=d, check=False)
        msgs = []
        for f in glob.glob(str(d / "chat.*.json")):
            msgs += sig.parse_twitch_chat(f)
        found.append(f"{sc.chat(msgs)} chat messages")

    # Loudness of the whole stream: always for files and Kick, and as a backup when signals are thin.
    thin = len(sc.peaks(n=40, gap=gap)) < 15
    if m["kind"] in ("file", "kick", "other") or thin:
        audio = m["url"] if m["kind"] == "file" else ensure_audio(m)
        step("Scanning the whole stream for loud reactions")
        sc.loudness(audio)
        found.append("loudness scan")
    log("Signals: " + ", ".join(found))
    return sc.peaks(n=200, gap=gap, exclude=exclude)


def ensure_audio(m):
    d = stream_dir(m["id"])
    got = glob.glob(str(d / "audio.*"))
    if got:
        return got[0]
    step("Downloading audio only (much smaller than the video)")
    ytdlp("-f", "ba[abr<=96]/ba/worstaudio/worst", "-o", "audio.%(ext)s", "--", m["url"], cwd=d)
    return glob.glob(str(d / "audio.*"))[0]


def init_queue(m):
    q = queue(m["id"])
    if q:
        return q
    q = build_queue(m)
    save_queue(m["id"], q)
    log(f"Found {len(q)} possible moments")
    return q


def widen_queue(m):
    q = queue(m["id"])
    step("Few moments left, searching the stream again more closely")
    extra = build_queue(m, gap=30, exclude=[e["t"] for e in q])
    q += extra
    save_queue(m["id"], q)
    log(f"Added {len(extra)} more possible moments")
    return len(extra)


# ---------------------------------------------------------------- step 3: download windows
def window_range(m, t):
    w0 = max(0, t - 35)
    return w0, min(m["duration"], w0 + 60)


def download_windows(m, entries):
    d = stream_dir(m["id"]) / "windows"
    d.mkdir(exist_ok=True)
    todo = []
    for e in entries:
        w0, w1 = window_range(m, e["t"])
        e["w0"] = w0
        e["win"] = str(d / f"win_{int(w0)}.mp4")
        if not os.path.exists(e["win"]):
            todo.append((e, w0, w1))
    if not todo:
        return
    step(f"Downloading {len(todo)} short window(s) around the moments")
    if m["kind"] == "file":
        for e, w0, w1 in todo:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(w0), "-i", m["url"], "-t", str(w1 - w0),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac", "-b:a", "192k",
                            e["win"]], check=True)
        return
    args = ["-N", "8", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--force-keyframes-at-cuts",
            "-o", "win_%(section_start)d.%(ext)s"]
    for _, w0, w1 in todo:
        args += ["--download-sections", f"*{int(w0)}-{int(w1)}"]
    r = ytdlp(*args, "--", m["url"], cwd=d, check=False)
    missing = [e for e, _, _ in todo if not os.path.exists(e["win"])]
    if missing:
        msg = (r.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        if "403" in msg[0]:
            msg = ["YouTube said 403. Very long streams that just ended can take a few hours to process. Try again later."]
        log(f"Could not download {len(missing)} window(s): {msg[0]}")
        for e in missing:
            e["win"] = None


# ---------------------------------------------------------------- layout (facecam + gameplay boxes)
LAYOUT_EVENT = threading.Event()


def layouts():
    return jload(LAYOUTS, {})


def layout_for(m, frame_wh):
    lay = layouts().get(m["channel"])
    if not lay:
        return None
    fw, fh = lay["frame"]
    sx, sy = frame_wh[0] / fw, frame_wh[1] / fh
    s = lambda b: [round(b[0] * sx), round(b[1] * sy), round(b[2] * sx), round(b[3] * sy)] if b else None
    return {"face": s(lay["face"]), "game": s(lay["game"])}


def save_layout(channel, frame_wh, face, game):
    with LOCK:
        L = layouts()
        L[channel] = {"frame": list(frame_wh), "face": face, "game": game}
        jsave(LAYOUTS, L)
    LAYOUT_EVENT.set()


def default_layout(w, h):
    gw = int(h * 0.915) if w > h * 0.915 else w
    return {"face": None, "game": [(w - gw) // 2, 0, gw, h]}


def ensure_layout(m, win):
    _, wh = probe(win)
    lay = layout_for(m, wh)
    if lay:
        return lay
    d = stream_dir(m["id"])
    frame = d / "frame.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "20", "-i", win, "-frames:v", "1", "-q:v", "3", str(frame)], check=True)
    suggest = default_layout(*wh)
    if ai_on():
        try:
            step("Asking Claude where the facecam is")
            s = claude_ai.suggest_layout(settings()["api_key"], settings()["model"], frame, *wh)
            suggest = {"face": s.get("face"), "game": s.get("game") or suggest["game"]}
        except Exception as ex:
            log(f"Claude could not find the layout ({ex}). Please mark it yourself.")
    m["needs_layout"] = {"frame_wh": list(wh), "suggest": suggest}
    save_meta(m)
    step("Waiting for you: mark the facecam and gameplay areas")
    LAYOUT_EVENT.clear()
    while not layout_for(m, wh):
        LAYOUT_EVENT.wait(1)
    m.pop("needs_layout", None)
    save_meta(m)
    log("Layout saved for " + m["channel"])
    return layout_for(m, wh)


# ---------------------------------------------------------------- step 4/5: check a moment and plan the clip
HOOKS = {
    "retention": ["Everyone kept rewatching this part", "Nobody saw this coming", "Wait for the ending"],
    "chat": ["Chat could not believe this", "Chat went crazy over this", "This had chat screaming"],
    "comments": ["The whole comment section talked about this", "Fans won't stop talking about this"],
    "loud": ["He was NOT ready for this", "This made him lose it", "Turn your sound up for this"],
}
TITLES = ["{s} Was Not Ready For This in GTA", "{s} Completely Loses It in GTA", "{s} Did Not See This Coming",
          "{s} Can't Believe What Just Happened", "This GTA Moment Broke {s}", "{s} Reacts to the Craziest GTA Moment"]


def frames_for(win, length, n=8, outdir=None):
    out = []
    for i in range(n):
        t = (i + 0.5) * length / n
        p = Path(outdir) / f"f{i}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", win, "-frames:v", "1",
                        "-vf", "scale=640:-2", "-q:v", "5", str(p)], check=True)
        out.append((t, str(p)))
    return out


def snap_clip(words, start, end, length):
    """Keep 15-45 s, and don't cut in the middle of a word."""
    for w in words:
        if w["s"] < start < w["e"]:
            start = w["s"] - 0.15
        if w["s"] < end < w["e"]:
            end = w["e"] + 0.2
    start, end = max(0.0, start), min(length, end)
    if end - start < 15:
        need = 15 - (end - start)
        start = max(0.0, start - need * 0.4)
        end = min(length, start + 15)
        start = max(0.0, end - 15)
    if end - start > 45:
        end = start + 45
    return round(start, 2), round(end, 2)


def plan_auto(e, words, length, face_mot, used_hooks):
    """No-API mode: pick the loudest reaction near the flagged time."""
    loud = sig.loudness_per_second(e["win"])
    if not len(loud):
        return None, "no audio"
    med = np.median(loud)
    sc = np.maximum(0, loud - med)
    if len(face_mot):
        per_sec = np.array([face_mot[i * 4:(i + 1) * 4].mean() if len(face_mot[i * 4:(i + 1) * 4]) else 0 for i in range(len(loud))])
        sc = sc + 3 * np.maximum(0, per_sec / (np.median(per_sec) + 1e-6) - 2)
    c = e["t"] - e["w0"]
    lo, hi = int(max(0, c - 28)), int(min(len(sc), c + 12))
    if hi <= lo:
        lo, hi = 0, len(sc)
    p = lo + int(np.argmax(sc[lo:hi]))
    if loud[p] - med < 7 and sc[p] < 8:
        return None, "no big reaction"
    start, end = snap_clip(words, p - 9, p + 8, length)
    # let the clip run on while he keeps talking
    for w in words:
        if end - 0.6 < w["s"] < start + 40:
            end = max(end, min(w["e"] + 0.3, start + 45))
    said = [w for w in words if start <= w["s"] < end]
    if len(said) < 4:
        return None, "no streamer reaction"
    tag = next((k for k in ("retention", "chat", "comments", "loud") if k in e["why"]), "loud")
    hook = next((h for h in HOOKS[tag] if h not in used_hooks), HOOKS[tag][0])
    near = [w["w"] for w in words if abs(w["s"] - p) < 3][:8]
    return {"start": start, "end": round(end, 2), "hook": hook, "caption": " ".join(near).capitalize() or hook,
            "title": None, "game_dialogue": [], "fixes": {}}, "loud reaction"


def process_entry(m, e, lay, used_hooks, used_titles):
    win = e["win"]
    length, _ = probe(win)
    block = blocked_words()
    step(f"Checking moment at {hms(e['t'])}: transcribing")
    words = asr.transcribe(win, log=log)
    if block and any(b in " ".join(w["w"].lower() for w in words) for b in block):
        return None, "blocked word"
    face_mot = sig.face_motion(win, lay["face"]) if lay["face"] else np.zeros(0)
    if ai_on():
        step(f"Checking moment at {hms(e['t'])}: asking Claude")
        tmp = stream_dir(m["id"]) / "frames"
        tmp.mkdir(exist_ok=True)
        try:
            plan = claude_ai.judge_moment(settings()["api_key"], settings()["model"],
                                          frames_for(win, length, 8, tmp), words, m["channel"], e["why"], length)
        except Exception as ex:
            log(f"Claude check failed ({ex}), using automatic mode for this one")
            plan, why = plan_auto(e, words, length, face_mot, used_hooks)
            if not plan:
                return None, why
        else:
            if not plan.get("keep"):
                return None, (plan.get("reason") or "not clip-worthy")[:40]
            plan["start"], plan["end"] = snap_clip(words, float(plan["start"]), float(plan["end"]), length)
    else:
        plan, why = plan_auto(e, words, length, face_mot, used_hooks)
        if not plan:
            return None, why

    # Captions: streamer words only, fixed and censored
    drop = {int(i) for i in plan.get("game_dialogue") or [] if str(i).lstrip("-").isdigit()}
    fixes = {int(k): v for k, v in (plan.get("fixes") or {}).items() if str(k).isdigit()}
    cap_words = [dict(w, w=censor(fixes.get(i, w["w"]))) for i, w in enumerate(words) if i not in drop]

    # Sync check (mouth vs voice); only trust a clear result
    lag = 0.0
    if lay["face"]:
        try:
            l, c = av_lag.measure_mouth(win, max(0, plan["start"]), min(20, length - plan["start"] - 4), *lay["face"])
            if c >= 0.15 and 0.04 < abs(l) < 1.0:
                lag = l
                log(f"Fixed audio/video offset of {l:+.2f}s")
        except Exception:
            pass

    n = m["next_n"]
    title = plan.get("title") or next((t for t in TITLES if t.format(s=m["channel"]) not in used_titles), TITLES[0]).format(s=m["channel"])
    tag_name = "#" + re.sub(r"\W", "", m["channel"])
    clip = {"n": n, "t": e["t"], "source_time": hms(e["w0"] + plan["start"]), "why": e["why"],
            "hook": " ".join((plan.get("hook") or "").split()[:9]), "title": title[:60],
            "caption": plan.get("caption") or "", "hashtags": plan.get("hashtags") or ["#GTA6", "#GTAVI", tag_name, "#Gaming", "#Shorts"],
            "start": plan["start"], "end": plan["end"], "win": win, "w0": e["w0"], "av_lag": lag,
            "face": lay["face"], "game": lay["game"], "words": cap_words}
    if clip["hashtags"] and tag_name not in clip["hashtags"] and "#Streamer" in clip["hashtags"]:
        clip["hashtags"] = [tag_name if h == "#Streamer" else h for h in clip["hashtags"]]
    step(f"Rendering clip {n}: {clip['title']}")
    render_one(m, clip)
    return clip, "kept"


def render_one(m, clip):
    name = f"{slug(m['channel'], 20)}_{clip['n']:02d}_{slug(clip['title'], 30)}.mp4"
    out = CLIPS / slug(m["id"], 60) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    old = clip.get("file")
    if old and Path(old) != out:
        for f in (old, clip.get("thumb")):
            if f and os.path.exists(f):
                os.remove(f)
    render_clip.render({"src": clip["win"], "t0": clip["start"], "t1": clip["end"], "out": str(out),
                        "face": clip["face"], "game": clip["game"], "face_h": FACE_H, "hook": clip["hook"],
                        "words": clip["words"], "av_lag": clip["av_lag"]})
    thumb = out.with_suffix(".jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "3.6", "-i", str(out), "-frames:v", "1",
                    "-vf", "scale=360:-2", "-q:v", "4", str(thumb)], check=True)
    clip["file"], clip["thumb"] = str(out), str(thumb)
    clip["rendered"] = time.time()


# ---------------------------------------------------------------- one batch ("10 clips" / "more")
def run_batch(url_or_id, count=10):
    m = meta(url_or_id) or open_stream(url_or_id)
    PROGRESS["stream"] = m["id"]
    step(f"Working on: {m['title']}")
    q = init_queue(m)
    made, widened = 0, False
    used_hooks = {c["hook"] for c in m["clips"]}
    used_titles = {c["title"] for c in m["clips"]}
    lay = None
    while made < count:
        q = queue(m["id"])
        group = sorted([e for e in q if e["status"] == "new"], key=lambda e: -e["score"])[:5]
        if not group:
            if not widened and widen_queue(m):
                widened = True
                continue
            m["used_up"] = True
            save_meta(m)
            log("This stream is used up. Try the streamer's previous or next stream.")
            break
        download_windows(m, group)
        for e in group:
            if made >= count:
                break
            qe = next(x for x in q if x["t"] == e["t"])
            if not e.get("win"):
                qe.update(status="skipped", reason="download failed")
                save_queue(m["id"], q)
                continue
            if lay is None:
                lay = ensure_layout(m, e["win"])
            try:
                clip, reason = process_entry(m, e, lay, used_hooks, used_titles)
            except Exception as ex:
                traceback.print_exc()
                clip, reason = None, f"error: {str(ex)[:60]}"
            if clip:
                made += 1
                m = meta(m["id"])
                m["clips"].append(clip)
                m["next_n"] = clip["n"] + 1
                save_meta(m)
                used_hooks.add(clip["hook"])
                used_titles.add(clip["title"])
                qe.update(status="done", n=clip["n"], title=clip["title"], file=clip["file"])
                log(f"Clip {clip['n']} ready")
            else:
                qe.update(status="skipped", reason=reason)
                log(f"Skipped {hms(e['t'])}: {reason}")
            save_queue(m["id"], q)
    left = sum(1 for e in queue(m["id"]) if e["status"] == "new")
    step(f"Done: {made} new clip(s). {left} moments left in the queue.")
    return m


def rerender(sid, n, changes):
    m = meta(sid)
    clip = next(c for c in m["clips"] if c["n"] == n)
    for k in ("hook", "title", "caption"):
        if k in changes:
            clip[k] = changes[k]
    if "hashtags" in changes:
        clip["hashtags"] = [h if h.startswith("#") else "#" + h for h in changes["hashtags"].split()]
    for k in ("start", "end"):
        if k in changes and changes[k] != "":
            clip[k] = float(changes[k])
    clip["start"], clip["end"] = snap_clip([], clip["start"], clip["end"], probe(clip["win"])[0])
    if any(k in changes for k in ("hook", "start", "end", "title")):
        step(f"Re-rendering clip {n}")
        render_one(m, clip)
    save_meta(m)
    step(f"Clip {n} updated")
