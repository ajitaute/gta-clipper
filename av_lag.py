"""Audio/video lag of a source (from the gta-clipping skill). Positive = VIDEO LAGS AUDIO.
av_lag.py mouth SRC START DUR FX FY FW FH
The app calls measure_mouth() directly."""
import sys, subprocess
import numpy as np


def _ff(args):
    return subprocess.run(["ffmpeg", "-v", "error"] + args, capture_output=True).stdout


def measure_mouth(src, a, dur, fx, fy, fw, fh):
    """Returns (lag_seconds, correlation). Correlation under 0.15 means 'not sure'."""
    F = 50
    v = _ff(["-ss", str(a), "-t", str(dur + 3.5), "-i", str(src), "-vf",
             f"fps={F},crop={fw}:{fh}:{fx}:{fy},crop=iw*0.36:ih*0.30:iw*0.32:ih*0.52,scale=64:40,format=gray",
             "-f", "rawvideo", "-"])
    fr = np.frombuffer(v, np.uint8)
    fr = fr[: len(fr) // 2560 * 2560].reshape(-1, 40, 64).astype(np.float32)
    if len(fr) < 4 * F:
        return 0.0, 0.0
    mot = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    s = np.frombuffer(_ff(["-ss", str(a), "-t", str(dur), "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                           "-af", "highpass=f=200,lowpass=f=3000", "-f", "s16le", "-"]), np.int16).astype(np.float32)
    h = 16000 // F
    env = np.log(np.array([np.sqrt(np.mean(s[i * h:(i + 1) * h] ** 2)) for i in range(len(s) // h)]) + 1)
    z = lambda x: (x - x.mean()) / (x.std() + 1e-6)
    res = []
    for k in range(-F, 3 * F + 1):
        m, e = (mot[k:], env) if k >= 0 else (mot, env[-k:])
        L = min(len(m), len(e)) - 1
        if L > 3 * F:
            res.append((float(np.corrcoef(z(m[:L]), z(e[:L]))[0, 1]), k / F))
    if not res:
        return 0.0, 0.0
    res.sort(reverse=True)
    c, lag = res[0]
    return lag, c


if __name__ == "__main__":
    lag, c = measure_mouth(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), *map(int, sys.argv[5:9]))
    print("lag", lag, "corr", round(c, 3), "" if c >= 0.15 else "| weak: pick a window where he talks")
