"""9:16 clip: facecam on top, gameplay below, word captions, hook card.
Based on render_clip.py from the gta-clipping skill.

spec = {src, t0, t1 (seconds in src), out, face:[x,y,w,h] or None, game:[x,y,w,h],
        face_h:740, hook, words:[{w,s,e}] (streamer words only, src seconds),
        av_lag:0.0, hook_y:600, hook_end:3.2}
"""
import json, sys, os, subprocess, re, shutil, platform
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
W, H, YEL = 1080, 1920, (255, 222, 0)
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf"
_font_path = None


def font_path():
    global _font_path
    if _font_path:
        return _font_path
    local = HERE / "fonts" / "Montserrat.ttf"
    for p in [os.environ.get("CLIP_FONT", ""), str(local),
              "/usr/share/fonts/truetype/google-fonts/ofl/montserrat/Montserrat[wght].ttf"]:
        if p and os.path.exists(p):
            _font_path = p
            return p
    try:  # one-time download of the clip font
        import urllib.request
        local.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(FONT_URL, local)
        _font_path = str(local)
        return _font_path
    except Exception:
        pass
    for p in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]:
        if os.path.exists(p):
            _font_path = p
            return p
    if shutil.which("fc-match"):
        _font_path = subprocess.run(["fc-match", "sans:bold", "--format=%{file}"], capture_output=True, text=True).stdout
        return _font_path
    raise RuntimeError("No bold font found. Put Montserrat.ttf in the fonts folder.")


def font(size):
    f = ImageFont.truetype(font_path(), size)
    try:
        f.set_variation_by_axes([900])
    except Exception:
        pass
    return f


def tw(d, s, f):
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def cap_png(words, act, path, size=86):
    im = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f, fa = font(size), font(int(size * 1.12))
    sp = int(size * 0.28)
    ws = [tw(d, w, fa if i == act else f) for i, w in enumerate(words)]
    tot = sum(ws) + sp * (len(words) - 1)
    if tot > W - 80:
        return cap_png(words, act, path, int(size * (W - 80) / tot))
    x = (W - tot) // 2
    for i, w in enumerate(words):
        ff = fa if i == act else f
        y = 120 - ff.size // 2 - (6 if i == act else 0)
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 4, y + 8), w, font=ff, fill=(0, 0, 0, 170), stroke_width=10, stroke_fill=(0, 0, 0, 170))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
        d.text((x, y), w, font=ff, fill=YEL if i == act else (255, 255, 255), stroke_width=9, stroke_fill=(0, 0, 0))
        x += ws[i] + sp
    im.save(path)


def hook_png(text, path):
    im = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(64)
    lines, cur = [], ""
    for w in (text or " ").split():
        t = (cur + " " + w).strip()
        if tw(d, t, f) > 880 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines.append(cur)
    bw = max(tw(d, l, f) for l in lines) + 70
    bh = 80 * len(lines) + 46
    x0 = (W - bw) // 2
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 6, 52, x0 + bw + 6, 52 + bh], 26, fill=(0, 0, 0, 140))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    d.rounded_rectangle([x0, 40, x0 + bw, 40 + bh], 26, fill=(255, 255, 255, 255))
    for i, l in enumerate(lines):
        d.text(((W - tw(d, l, f)) // 2, 60 + i * 80), l, font=f, fill=(12, 12, 12))
    im.save(path)


def groups(ws):
    g, cur = [], []
    for w in ws:
        if cur and (len(cur) >= 3 or w["s"] - cur[-1]["e"] > 0.45 or re.search(r"[.!?]$", cur[-1]["w"])):
            g.append(cur)
            cur = []
        cur.append(w)
    return g + ([cur] if cur else [])


def _p(path):  # ffmpeg concat files want forward slashes, also on Windows
    return Path(path).resolve().as_posix()


def render(S):
    t0, t1 = float(S["t0"]), float(S["t1"])
    dur = t1 - t0
    lag = float(S.get("av_lag", 0.0) or 0.0)
    wk = Path(S["out"] + "_work")
    wk.mkdir(parents=True, exist_ok=True)
    words = S["words"] if isinstance(S["words"], list) else json.load(open(S["words"]))
    ws = [dict(w, s=w["s"] - t0, e=min(w["e"] - t0, dur), w=re.sub(r"[^\w'’!?*-]", "", w["w"]).upper())
          for w in words if t0 - 0.05 <= w["s"] < t1]
    ws = [w for w in ws if w["w"]]

    blank = wk / "blank.png"
    Image.new("RGBA", (W, 260), (0, 0, 0, 0)).save(blank)
    seq, k = [], 0
    for g in groups(ws):
        for i, w in enumerate(g):
            p = wk / f"c{k:04d}.png"
            k += 1
            cap_png([x["w"] for x in g], i, p)
            end = g[i + 1]["s"] if i + 1 < len(g) else min(g[-1]["e"] + 0.25, dur)
            seq.append((p, w["s"], max(end, w["s"] + 0.08)))
    lst, t = [], 0.0
    for p, s, e in seq:
        if s > t + 0.01:
            lst.append((blank, s - t))
        s = max(s, t)
        if e > s:
            lst.append((p, e - s))
            t = e
    if dur > t:
        lst.append((blank, dur - t))
    with open(wk / "caps.txt", "w", encoding="utf-8") as f:
        for p, d in lst:
            f.write(f"file '{_p(p)}'\nduration {d:.4f}\n")
        f.write(f"file '{_p(lst[-1][0])}'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(wk / "caps.txt"),
                    "-vf", "fps=30,format=rgba", "-c:v", "qtrle", "-t", f"{dur:.3f}", str(wk / "caps.mov")], check=True)
    hook_png(S.get("hook", ""), wk / "hook.png")

    gx, gy, gw, gh = map(int, S["game"])
    he = float(S.get("hook_end", 3.2))
    face = S.get("face")
    if face:
        fx, fy, fw, fh = map(int, face)
        FH = int(S.get("face_h", 740))
        layout = (f"split=2[a][b];[a]crop={fw}:{fh}:{fx}:{fy},scale={W}:{FH}:flags=lanczos,setsar=1[f];"
                  f"[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{H - FH}:flags=lanczos,setsar=1[g];[f][g]vstack[s];"
                  f"[s]drawbox=x=0:y={FH - 3}:w={W}:h=6:color=black@0.9:t=fill[s2];")
        cap_y, hook_y = FH + 50, S.get("hook_y", 600)
    else:  # no facecam: gameplay fills the whole frame
        layout = f"crop={gw}:{gh}:{gx}:{gy},scale={W}:{H}:flags=lanczos,setsar=1[s2];"
        cap_y, hook_y = 1180, S.get("hook_y", 420)
    fc = (f"[0:v]trim=start={t0 + lag}:end={t1 + lag},setpts=PTS-STARTPTS,fps=30,{layout}"
          f"[s2][1:v]overlay=0:{cap_y}[s3];"
          f"[2:v]format=rgba,fade=t=out:st={he - 0.25}:d=0.25:alpha=1[hk];"
          f"[s3][hk]overlay=0:{hook_y}:enable='lte(t,{he})',format=yuv420p[v];"
          f"[0:a]atrim=start={t0}:end={t1},asetpts=PTS-STARTPTS,afade=t=in:d=0.08,afade=t=out:st={dur - 0.25}:d=0.25,"
          f"loudnorm=I=-14:TP=-1.2:LRA=11[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(S["src"]), "-i", str(wk / "caps.mov"),
                    "-loop", "1", "-t", f"{dur:.3f}", "-i", str(wk / "hook.png"),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart", "-t", f"{dur:.3f}", str(S["out"])], check=True)
    shutil.rmtree(wk, ignore_errors=True)
    return S["out"]


if __name__ == "__main__":
    print("rendered", render(json.load(open(sys.argv[1]))))
