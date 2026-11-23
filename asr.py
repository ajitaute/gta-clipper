"""Word timestamps with Parakeet via sherpa-onnx (from the gta-clipping skill).
Models come from GitHub (about 650 MB, downloaded once into ./models)."""
import os, json, shutil, tarfile, urllib.request, subprocess, tempfile, wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
M = HERE / "models"
R = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
_rec = None


def _download(url, dest, log=print):
    log(f"Downloading {url.rsplit('/', 1)[-1]} (one time only)...")
    tmp = str(dest) + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


def ensure_models(log=print):
    M.mkdir(exist_ok=True)
    if not (M / NAME).exists():
        arc = M / f"{NAME}.tar.bz2"
        if not arc.exists():
            _download(R + f"{NAME}.tar.bz2", arc, log)
        log("Unpacking speech model...")
        tmp = M / "_unpack"
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(arc, "r:bz2") as t:
            t.extractall(tmp)
        os.replace(tmp / NAME, M / NAME)  # only appears when fully unpacked
        shutil.rmtree(tmp, ignore_errors=True)
        arc.unlink()
    if not (M / "silero_vad.onnx").exists():
        _download(R + "silero_vad.onnx", M / "silero_vad.onnx", log)


def _recognizer():
    global _rec
    if _rec is None:
        import sherpa_onnx
        P = str(M / NAME) + os.sep
        _rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=P + "encoder.int8.onnx", decoder=P + "decoder.int8.onnx",
            joiner=P + "joiner.int8.onnx", tokens=P + "tokens.txt",
            num_threads=max(2, (os.cpu_count() or 4) // 2), model_type="nemo_transducer")
    return _rec


def transcribe(media, log=print):
    """Returns [{"w": word, "s": start, "e": end}] in the media file's own seconds."""
    import sherpa_onnx
    ensure_models(log)
    rec = _recognizer()
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        w = wave.open(wav)
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        w.close()
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(M / "silero_vad.onnx")
    cfg.sample_rate = 16000
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.max_speech_duration = 15
    cfg.silero_vad.threshold = 0.4
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=600)
    out = []

    def flush():
        while not vad.empty():
            seg = vad.front
            s = rec.create_stream()
            s.accept_waveform(16000, np.array(seg.samples))
            rec.decode_stream(s)
            off = seg.start / 16000
            cur = []
            for t, ts in zip(s.result.tokens, s.result.timestamps):
                if t.startswith("▁") or t.startswith(" ") or not cur:
                    cur.append({"w": t.lstrip("▁ "), "s": off + ts, "e": off + ts + 0.2})
                else:
                    cur[-1]["w"] += t
                    cur[-1]["e"] = off + ts + 0.2
            for i in range(len(cur) - 1):
                cur[i]["e"] = min(cur[i]["e"] + 0.15, cur[i + 1]["s"])
            out.extend(c for c in cur if c["w"])
            vad.pop()

    for i in range(0, len(a), 512):
        vad.accept_waveform(a[i:i + 512])
        flush()
    vad.flush()
    flush()
    return out


if __name__ == "__main__":
    import sys
    words = transcribe(sys.argv[1])
    json.dump(words, open(sys.argv[2], "w"))
    print(len(words), "words")
