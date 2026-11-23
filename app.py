"""GTA Clipper: local web app. Run start.bat (Windows) or start.sh, then open http://localhost:5000"""
import os, queue as Q, threading, traceback, webbrowser, shutil
from pathlib import Path
from flask import Flask, jsonify, request, send_file, abort

import pipeline as P
import claude_ai

HERE = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="static", static_url_path="/static")
JOBS = Q.Queue()
PENDING = []  # what's waiting, for the UI


def worker():
    while True:
        job = JOBS.get()
        P.PROGRESS.update(busy=True, error=None)
        try:
            if job["type"] == "batch":
                P.run_batch(job["target"], job.get("count", 10))
            elif job["type"] == "rerender":
                P.rerender(job["sid"], job["n"], job["changes"])
        except Exception as ex:
            traceback.print_exc()
            P.PROGRESS["error"] = str(ex)
            P.log("Error: " + str(ex))
        finally:
            if job in PENDING:
                PENDING.remove(job)
            P.PROGRESS.update(busy=bool(PENDING))


threading.Thread(target=worker, daemon=True).start()


def add_job(job):
    PENDING.append(job)
    JOBS.put(job)


@app.get("/")
def index():
    return send_file(HERE / "static" / "index.html")


@app.get("/api/state")
def state():
    streams = P.all_streams()
    for s in streams:
        for c in s["clips"]:
            c.pop("words", None)
            c.pop("win", None)
    return jsonify({"progress": P.PROGRESS, "pending": len(PENDING), "streams": streams,
                    "ai": P.ai_on(), "tools": {"ffmpeg": bool(shutil.which("ffmpeg"))}})


@app.post("/api/clip")
def start():
    d = request.get_json(force=True)
    target = (d.get("target") or "").strip().strip('"')
    if not target:
        return jsonify(error="Paste a stream link or a video file path first."), 400
    count = max(1, min(30, int(d.get("count") or 10)))
    add_job({"type": "batch", "target": target, "count": count})
    return jsonify(ok=True)


@app.post("/api/rerender")
def rerender():
    d = request.get_json(force=True)
    add_job({"type": "rerender", "sid": d["sid"], "n": int(d["n"]), "changes": d.get("changes", {})})
    return jsonify(ok=True)


@app.get("/api/frame/<sid>")
def frame(sid):
    p = P.STREAMS / sid / "frame.jpg"
    if not p.exists():
        abort(404)
    return send_file(p, max_age=0)


@app.post("/api/layout")
def layout():
    d = request.get_json(force=True)
    m = P.meta(d["sid"])
    if not m or not m.get("needs_layout"):
        return jsonify(error="Nothing is waiting for a layout."), 400
    P.save_layout(m["channel"], m["needs_layout"]["frame_wh"], d.get("face"), d["game"])
    return jsonify(ok=True)


@app.post("/api/forget-layout")
def forget_layout():
    d = request.get_json(force=True)
    L = P.layouts()
    L.pop(d.get("channel"), None)
    P.jsave(P.LAYOUTS, L)
    return jsonify(ok=True)


@app.get("/media/<sid>/<int:n>/<kind>")
def media(sid, n, kind):
    m = P.meta(sid) or abort(404)
    c = next((c for c in m["clips"] if c["n"] == n), None) or abort(404)
    p = c.get("thumb" if kind == "thumb" else "file")
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, as_attachment=(kind == "download"), download_name=os.path.basename(p), max_age=0)


@app.post("/api/save/<sid>/<int:n>")
def save_to_downloads(sid, n):
    m = P.meta(sid) or abort(404)
    c = next((c for c in m["clips"] if c["n"] == n), None) or abort(404)
    dest_dir = Path.home() / "Downloads"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / os.path.basename(c["file"])
    shutil.copy2(c["file"], dest)
    return jsonify(ok=True, path=str(dest))


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    s = P.settings()
    if request.method == "POST":
        d = request.get_json(force=True)
        key = (d.get("api_key") or "").strip()
        model = (d.get("model") or s.get("model") or "claude-sonnet-5-5").strip()
        if key and key != "keep":
            try:
                claude_ai.test_key(key, model)
            except Exception as ex:
                return jsonify(error=f"That key or model didn't work: {ex}"), 400
            s["api_key"] = key
        elif not key:
            s["api_key"] = ""
        s["model"] = model
        P.jsave(P.SETTINGS, s)
    return jsonify({"has_key": bool(s.get("api_key")), "model": s.get("model", "claude-sonnet-5-5")})


@app.post("/api/open-folder")
def open_folder():
    p = str(P.CLIPS)
    try:
        if os.name == "nt":
            os.startfile(p)
        elif shutil.which("open"):
            os.system(f'open "{p}"')
        else:
            os.system(f'xdg-open "{p}"')
    except Exception:
        pass
    return jsonify(ok=True, path=p)


if __name__ == "__main__":
    import socket
    port = int(os.environ.get("PORT", 5000))
    # On Mac, port 5000 is often taken by AirPlay Receiver, so find a free one
    for _ in range(20):
        with socket.socket() as sk:
            if sk.connect_ex(("127.0.0.1", port)) != 0:
                break
        port += 1
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"GTA Clipper running at http://localhost:{port}  (close this window to stop)")
    app.run(host="127.0.0.1", port=port, threaded=True)
