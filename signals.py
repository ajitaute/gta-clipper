"""Find clip-worthy moments in a stream from cheap signals.

Based on moments.py from the gta-clipping skill, turned into functions so the
app can mix whatever signals a stream has (YouTube, Twitch, Kick or a local file).
All times are in source seconds.
"""
import json, re, math, statistics, subprocess
from collections import Counter

import numpy as np

BIN = 5
HYPE = re.compile(r"LMA+O|LO+L|😂|🤣|💀|NO+ ?WA+Y|CLIP|WTF|OMG|BRO+|CRAZY|AYO+|🔥|GOAT|W+ ", re.I)
TIMESTAMP = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")


class Scorer:
    def __init__(self, duration):
        self.nb = int(duration // BIN) + 2
        self.sc = [0.0] * self.nb
        self.why = [set() for _ in range(self.nb)]

    def add(self, t, v, tag):
        b = int(t // BIN)
        if 0 <= b < self.nb and v > 0:
            self.sc[b] += v
            self.why[b].add(tag)

    # --- signals -----------------------------------------------------------
    def heatmap(self, hm):
        """YouTube 'Most replayed' data: list of {start_time, end_time, value}."""
        if not hm:
            return 0
        vals = [h["value"] for h in hm]
        med, top = statistics.median(vals), max(vals)
        for h in hm:
            for t in range(int(h["start_time"]), int(h["end_time"]) + 1, BIN):
                self.add(t, 4 * (h["value"] - med) / (top - med + 1e-9), "retention")
        return len(hm)

    def chat(self, messages):
        """messages: list of (t_seconds, text). Chat reacts 5-15 s late, so shift back."""
        if not messages:
            return 0
        cnt, hy = Counter(), Counter()
        for t, txt in messages:
            b = int(t // BIN)
            cnt[b] += 1
            hy[b] += bool(HYPE.search(txt or ""))
        for b in range(self.nb):
            base = max(statistics.median([cnt.get(k, 0) for k in range(max(0, b - 36), b)] or [1]), 1)
            r = cnt.get(b, 0) / base
            self.add(b * BIN - 10, 1.5 * max(0, r - 1.3) + hy.get(b, 0) / max(cnt.get(b, 1), 1), "chat")
        return len(messages)

    def comments(self, comments):
        """YouTube comments with timestamps like 1:23:45 in them."""
        n = 0
        for c in comments or []:
            hits = list(TIMESTAMP.finditer(c.get("text", "") or ""))
            if not hits or len(hits) > 2:
                continue
            for m in hits:
                t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                self.add(t, 0.6 + math.log10((c.get("like_count") or 0) + 1) / 2, "comments")
                n += 1
        return n

    def loudness(self, media, offset=0.0):
        """Voice/game loudness spikes, one value per second."""
        rms = loudness_per_second(media)
        if not len(rms):
            return 0
        med = np.median(rms)
        for i, v in enumerate(rms):
            self.add(offset + i, max(0, (v - med - 6) / 6), "loud")
        return len(rms)

    # --- ranking -----------------------------------------------------------
    def peaks(self, n=200, gap=45, exclude=()):
        sm = [sum(self.sc[max(0, i - 1):i + 2]) for i in range(self.nb)]
        picked = []
        for i in sorted(range(self.nb), key=lambda i: -sm[i]):
            if sm[i] <= 0 or any(abs(i - j) * BIN < gap for j in picked):
                continue
            if any(abs(i * BIN - t) < gap for t in exclude):
                continue
            picked.append(i)
            if len(picked) >= n:
                break
        out = []
        for i in picked:
            r = set().union(*self.why[max(0, i - 1):i + 2])
            out.append({"t": i * BIN, "score": round(sm[i], 2), "why": sorted(r), "status": "new"})
        return out


# --- parsers for the files yt-dlp writes ------------------------------------
def parse_youtube_chat(path, rec_start_ms=None):
    msgs = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            j = json.loads(line)
        except Exception:
            continue
        r = j.get("replayChatItemAction", {})
        off = r.get("videoOffsetTimeMsec")
        for a in r.get("actions", []) or [j]:
            it = a.get("addChatItemAction", {}).get("item", {})
            m = it.get("liveChatTextMessageRenderer") or it.get("liveChatPaidMessageRenderer")
            if not m:
                continue
            if off is not None:
                t = int(off) / 1000
            elif rec_start_ms:
                t = (int(m.get("timestampUsec", 0)) / 1000 - rec_start_ms) / 1000
            else:
                continue
            txt = "".join(x.get("text", "") for x in m.get("message", {}).get("runs", []))
            msgs.append((t, txt))
    return msgs


def parse_twitch_chat(path):
    """Twitch 'rechat' as saved by yt-dlp. The format has changed over the years,
    so this is tolerant and simply looks for an offset and a message body."""
    msgs = []
    try:
        data = json.load(open(path, encoding="utf-8", errors="ignore"))
    except Exception:
        return msgs
    items = data.get("comments", data) if isinstance(data, dict) else data
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict):
            continue
        t = c.get("content_offset_seconds") or c.get("contentOffsetSeconds")
        msg = c.get("message") or {}
        txt = msg.get("body") if isinstance(msg, dict) else str(msg)
        if txt is None and isinstance(msg, dict):
            txt = "".join(f.get("text", "") for f in msg.get("fragments", []) or [])
        if t is not None:
            msgs.append((float(t), txt or ""))
    return msgs


def loudness_per_second(media, start=None, dur=None):
    args = ["ffmpeg", "-v", "error"]
    if start is not None:
        args += ["-ss", str(start)]
    if dur is not None:
        args += ["-t", str(dur)]
    args += ["-i", str(media), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    au = subprocess.run(args, capture_output=True).stdout
    x = np.frombuffer(au, np.int16).astype(np.float32)
    sec = 8000
    return np.array([20 * np.log10(np.sqrt(np.mean(x[i * sec:(i + 1) * sec] ** 2)) + 1e-6)
                     for i in range(len(x) // sec)])


def face_motion(media, face, fps=4):
    """Facecam motion per frame (fps per second). Big jumps = big reactions."""
    fx, fy, fw, fh = map(int, face)
    v = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vf",
                        f"fps={fps},crop={fw}:{fh}:{fx}:{fy},scale=48:32,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True).stdout
    if not v:
        return np.zeros(0)
    fr = np.frombuffer(v, np.uint8)
    fr = fr[: len(fr) // (32 * 48) * (32 * 48)].reshape(-1, 32, 48).astype(np.float32)
    if len(fr) < 2:
        return np.zeros(0)
    return np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
