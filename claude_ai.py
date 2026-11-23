"""Optional Claude API helpers. Only used when an API key is saved in Settings."""
import base64, json, re
import requests

API = "https://api.anthropic.com/v1/messages"


def _call(key, model, content, max_tokens=1500):
    r = requests.post(API, timeout=120, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]})
    if r.status_code != 200:
        raise RuntimeError(f"Claude API error {r.status_code}: {r.text[:300]}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _img(path):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(open(path, "rb").read()).decode()}}


def test_key(key, model):
    _call(key, model, [{"type": "text", "text": 'Reply with exactly {"ok": true}'}], 50)
    return True


def suggest_layout(key, model, frame_path, fw, fh):
    prompt = f"""This is one frame ({fw}x{fh} pixels) of a GTA livestream.
Find the streamer's facecam (webcam showing the person) if there is one, and the main gameplay area.
Reply ONLY with JSON:
{{"face": [x, y, w, h] or null, "game": [x, y, w, h]}}
Pixel coordinates in this frame. The facecam box should tightly cover the webcam overlay.
The game box is the full game area (not the facecam, not chat overlays)."""
    return _call(key, model, [_img(frame_path), {"type": "text", "text": prompt}], 300)


def judge_moment(key, model, frames, words, streamer, signals, win_len):
    """frames: list of (seconds, jpg_path). words: list of {w,s,e} in window seconds."""
    tr = "\n".join(f"{i}: [{w['s']:.2f}-{w['e']:.2f}] {w['w']}" for i, w in enumerate(words)) or "(no speech found)"
    content = []
    for t, p in frames:
        content.append({"type": "text", "text": f"Frame at {t:.1f}s"})
        content.append(_img(p))
    content.append({"type": "text", "text": f"""You are picking short-form clips (YouTube Shorts / TikTok) from a GTA livestream by {streamer}.
This window is {win_len:.0f} seconds long. Signals that flagged it: {', '.join(signals) or 'none'}.

Transcript with word index and time (seconds in this window). It may include game character dialogue
and some misheard words:
{tr}

Decide if this window has a clip worth posting. Keep it only if a stranger gets it in 1-2 seconds and
it has a payoff: a scream or big laugh, a fail, a plot twist, rage, a crazy stunt, or a wholesome or emotional beat.
Reject: sexual scenes, slurs, private info, long dialogue that needs more than 5 s of setup, pure gameplay with no reaction.

Reply ONLY with JSON:
{{
 "keep": true/false,
 "reason": "max 6 words",
 "start": seconds (cold open: 1-3 s before the action),
 "end": seconds (right after the payoff; clip 15-45 s long),
 "hook": "hook text, 9 words or fewer, no emoji",
 "title": "max 60 chars: {streamer} + what happens",
 "caption": "one caption line",
 "hashtags": ["#GTA6", "#GTAVI", "#Streamer", "#Gaming", "#Shorts"],
 "game_dialogue": [list of word indexes that are game characters talking, not the streamer],
 "fixes": {{"word index": "corrected word"}}
}}
Hook, title and caption must be clean English. Swears in fixes should be censored like F*** or S***."""})
    return _call(key, model, content, 1500)
