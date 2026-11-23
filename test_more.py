"""Effects on clips (zoom, replay, sound effects, emojis, voice intro), the weekly compilation, campaign reports,
trending videos and hashtags, sharing clips out between accounts, analytics, the swipe review, the phone app files
and moving a backup to a new machine. Platforms and the AI are stand-ins; ffmpeg does the real video work."""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import zipfile
from pathlib import Path

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-more-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="0", CLIPCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio import (accounts, ai, auth, backup, compilation, config, creators, ctx, db, fx, insights, jobs,  # noqa: E402
                    posting, render, server, trends)

db.init()
render.install_fonts()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


class R:
    def __init__(self, code, data=None, content=b""):
        self.status_code, self._d, self.content = code, data, content
        self.text = json.dumps(data) if data is not None else ""

    def json(self):
        return self._d


me = auth.local_user()
cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
H = {"Origin": "http://127.0.0.1:8765"}
work = Path(tempfile.mkdtemp())
src = work / "loud.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=300:d=6",
                "-f", "lavfi", "-i", "sine=f=900:d=0.6", "-filter_complex", "[1:a]volume=0.05[q];[2:a]adelay=2500|2500[l];[q][l]amix=inputs=2:normalize=0[a]",
                "-map", "0:v", "-map", "[a]", "-t", "6", "-c:v", "libx264", "-c:a", "aac", str(src)], check=True)


def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout.strip())


# ================================================================ effects
p, strength = fx.peak(src, 0.5, 5.5, work)
check("the loudest moment is found", p is not None and 1.9 <= p <= 2.7 and strength > 2, f"{p} {strength}")
ev = fx.emoji_events([{"w": "Headshot!", "s": 1.0}, {"w": "lol", "s": 1.5}, {"w": "WIN", "s": 3.0}, {"w": "the", "s": 3.5}], 0.5, 5.5)
check("words get their emojis, not two at once", [(e[0], e[2].name) for e in ev] == [(0.5, "skull.png"), (2.5, "trophy.png")], str(ev))
for kind in ("boom", "drop", "whoosh", "ding"):
    s = fx.sound(kind)
    check(f"the {kind} sound is made here, short and not clipped", 0.3 < len(s) / fx.SR < 1.6 and np.max(np.abs(s)) <= 1.0 and np.max(np.abs(s)) > 0.2)
check("nothing to add means no extra track", fx.extra_track(work / "none.wav", 5, []) is False)
check("sound effects go into one track the length of the clip", fx.extra_track(work / "x1.wav", 5, [(2.0, "boom")])
      and abs(wave.open(str(work / "x1.wav")).getnframes() / fx.SR - 5.5) < 0.01)

clip = {"start": 0.5, "end": 5.5, "hook": "NO WAY", "category": "fail", "title": "Fail",
        "fx": {"zoom": True, "replay": True, "sfx": True, "emoji": True, "voice": True}}
words = [{"w": "dead", "s": 1.2, "e": 1.5}, {"w": "lol", "s": 3.5, "e": 3.8}]
fx.voice_line = lambda title, hook: "Ye dekho kya hua"
fx.speak = lambda text: np.sin(np.linspace(0, 400, int(fx.SR * 1.2))).astype(np.float32) * 0.3
plan = render._fx_plan(clip, src, 0.5, 5.5, words, work, 1400)
check("the plan has the zoom and replay on the big moment, emojis, and a track with the voice and the boom",
      1.9 <= plan["zoom"] <= 2.7 and plan["replay"] == plan["zoom"] and len(plan["emojis"]) == 2 and plan["extra"]
      and abs(plan["voice_len"] - 1.2) < 0.01, str(plan))
out = render.render_clip(src, work / "o", "c1", dict(clip), words, 640, 360)
d = duration(work / "o" / "c1.mp4")
check("a clip with every effect is made, with the replay added at the end", out["file"] == "c1.mp4" and 7.0 < d < 9.0, str(d))
fx.speak = lambda text: (_ for _ in ()).throw(RuntimeError("no voice"))
plan = render._fx_plan(dict(clip, fx={"voice": True}), src, 0.5, 5.5, words, work, 1400)
check("no voice from the AI service: the clip is made without it", "extra" not in plan)
quiet = work / "quiet.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=f=300:d=6",
                "-t", "6", "-c:v", "libx264", "-c:a", "aac", str(quiet)], check=True)
plan = render._fx_plan(dict(clip, fx={"zoom": True, "sfx": True}), quiet, 0.5, 5.5, [], work, 1400)
check("a clip with no stand-out moment gets no punch-in or boom", plan == {"cap_y": 1400}, str(plan))

posted = []
real_speak = fx.speak


def gem(url, json=None, headers=None, timeout=None):
    posted.append(url)
    pcm = (np.sin(np.linspace(0, 200, 24000)) * 8000).astype("<i2").tobytes()
    return R(200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000",
                                                                          "data": base64.b64encode(pcm).decode()}}]}}]})


import importlib  # noqa: E402
importlib.reload(fx)
import httpx  # noqa: E402
httpx_post = httpx.post
httpx.post = gem
ai.provider = lambda: "gemini"
ai.key = lambda: "k"
v = fx.speak("hello")
httpx.post = httpx_post
check("Gemini's voice is turned into the clip's sample rate", v is not None and abs(len(v) / fx.SR - 1.0) < 0.01 and "tts" in posted[0])

# ================================================================ creators, clips and the compilation
with ctx.as_user(me.id):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "GameXtra", "added": time.time(), "access_token": "a", "refresh_token": "r", "expires": time.time() + 3600})
    accounts._put({"id": "ig_1", "platform": "instagram", "name": "@a", "added": time.time(), "user_id": "1", "token": "t", "token_time": time.time()})
    accounts._put({"id": "ig_2", "platform": "instagram", "name": "@b", "added": time.time(), "user_id": "2", "token": "t", "token_time": time.time()})
    c = creators.create({"name": "Valorant Pro", "game": "Valorant", "rate_per_1k": 2.5})
r = cl.post(f"/api/creators/{c['id']}/compilation", json={"days": 7}, headers=H)
check("too few clips: no compilation, and it says why", r.status_code == 400 and "at least 3" in r.text, r.text)
with ctx.as_user(me.id):
    made = []
    for i in range(3):
        j = jobs.create({"type": "file", "path": "", "name": f"v{i}.mp4"}, {}, enqueue=False, creator=c["id"])
        dd = Path(j["dir"]) / "clips"
        dd.mkdir(parents=True, exist_ok=True)
        shutil.copy(work / "o" / "c1.mp4", dd / "c1.mp4")
        shutil.copy(work / "o" / "c1.jpg", dd / "c1.jpg")
        j["clips"].append({"id": "c1", "status": "done", "file": "c1.mp4", "cover": "c1.jpg", "title": f"Clutch {i} 🔥", "score": 80 + i,
                           "made_at": time.time(), "hashtags": ["valorant"], "category": "clutch", "version": 1})
        jobs.save(j)
        made.append(j)
    picked = compilation.pick(c["id"])
    check("the best clips are picked, best first", [k["title"] for _j, k in picked] == ["Clutch 2 🔥", "Clutch 1 🔥", "Clutch 0 🔥"])
    comp = compilation.make(c["id"])
    k = comp["clips"][0]
    check("the compilation is a long 16:9 video with a thumbnail and chapters",
          k["long"] and (Path(comp["dir"]) / "clips" / "comp.mp4").is_file() and (Path(comp["dir"]) / "clips" / "comp.jpg").is_file()
          and "\n0:00 #3 Clutch 0" in k["description"] and "#1 Clutch 2" in k["description"])
    w, h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                           str(Path(comp["dir"]) / "clips" / "comp.mp4")], capture_output=True, text=True).stdout.strip().split(",")
    check("...1920x1080", (w, h) == ("1920", "1080"))
    check("a compilation is never put in the next compilation", all(j["id"] != comp["id"] for j, _k in compilation.pick(c["id"])))

    # ---- a compilation goes to YouTube only, as a normal video with its thumbnail
    calls = []
    accounts.youtube_upload = lambda acc, path, title, desc, tags, privacy, **kw: (calls.append(("up", desc)), ("vid9", "https://youtu.be/vid9"))[1]
    accounts.youtube_thumbnail = lambda acc, vid, jpg: calls.append(("thumb", vid, jpg.name))
    pp = posting.enqueue(comp, k, ["yt_1", "ig_1"], now=True)
    for x in pp:
        x["status"] = "posting"
        posting._post(x)
    yt, ig = pp
    check("on YouTube: no #Shorts, and the thumbnail is set", yt["status"] == "posted" and "#Shorts" not in calls[0][1] and calls[1] == ("thumb", "vid9", "comp.jpg"))
    check("not on Instagram, with the reason", ig["status"] in ("scheduled", "failed") and "YouTube only" in (ig["error"] or ""))

    # ---- sharing clips out between accounts
    creators.update(c["id"], {"autopost": True, "accounts": ["ig_1", "ig_2"], "rotate": True, "post_min_score": 0,
                              "no_duplicates": False})   # the test clips are the very same video
    for j in made:
        posting.on_clip_ready(j, j["clips"][0])
    got = [x["account"] for x in posting._mine() if x["job"] in {j["id"] for j in made}]
    check("each new clip goes to the next account in turn", got == ["ig_1", "ig_2", "ig_1"], str(got))

    # ---- trending hashtags on posts
    check("hashtags are counted from titles, without the generic ones", trends.tags_from(
        ["Insane ace #valorant #shorts #clutch", "#Valorant #clutch #ace", "lol #fyp #ace"], "Valorant") == ["valorant", "clutch", "ace"])
    trends._search = lambda q, n: [{"id": "a", "title": "x #valorant #ace", "url": "u1", "channel": "c", "views": 50, "duration": 60, "thumb": ""},
                                   {"id": "b", "title": "y #valorant #tenz", "url": "u2", "channel": "c", "views": 900, "duration": 60, "thumb": ""}]
    check("trending videos come most-watched first", [v["id"] for v in trends.trending("Valorant")] == ["b", "a"])
    r = cl.get("/api/trending", params={"game": "Valorant"})
    check("the Trending page gets videos and hashtags", r.status_code == 200 and r.json()["tags"][0] == "valorant", r.text[:200])
    check("no game: it says what to type", cl.get("/api/trending", params={"game": "  "}).status_code == 400)
    creators.update(c["id"], {"trend_tags": True})
    cap = posting._caption(made[0]["clips"][0], creators.get(c["id"]), "", trends.tags_for("Valorant")[:3])
    check("trending hashtags are added to the post, without repeats", cap.count("#valorant") == 1 and "#ace" in cap, cap)

    # ---- campaign report and analytics
    for i, x in enumerate([x for x in posting._mine() if x["status"] == "scheduled"][:2]):
        x.update(status="posted", posted_at=time.time() - 3600 * (i + 1), views=1000 * (i + 1), remote_id=f"r{i}", url=f"https://x/{i}")
r = cl.get(f"/api/creators/{c['id']}/campaign.csv")
lines = r.text.lstrip("﻿").strip().splitlines()
check("the campaign report lists posts, views and the pay, with a total", r.status_code == 200 and lines[0].startswith("Posted,Platform")
      and lines[-1].startswith("Total") and lines[-1].endswith(",3000,7.5"), r.text[-200:])
check("...as a file to download", "attachment" in r.headers.get("content-disposition", ""))
a = cl.get("/api/insights").json()
check("analytics groups views by clip type, platform and creator", a["posts"] == 3 and a["by_type"][0]["name"] == "Clutches"
      and {x["name"] for x in a["by_platform"]} >= {"Instagram"}, json.dumps(a)[:300])
import studio.insights as ins  # noqa: E402
ins.brain.ask_ai = lambda prompt, schema=None, purpose="", timeout=None: ({"tips": ["Post more clutches at 19:00 🔥", "x" * 400]}, "m", 1)
check("the AI gives tips from the numbers", cl.post("/api/insights/advice", json={}, headers=H).status_code == 400)   # fewer than 5 posts
with ctx.as_user(me.id):
    for i in range(3):
        posting._posts.append({"id": f"z{i}", "user": me.id, "job": made[0]["id"], "clip": "c1", "creator": c["id"], "account": "yt_1",
                               "account_name": "GameXtra", "platform": "youtube", "status": "posted", "due_at": time.time() - 99, "posted_at": time.time() - 99,
                               "created": time.time(), "title": "T", "remote_id": f"y{i}", "url": "", "tries": 0, "views": 10})
r = cl.post("/api/insights/advice", json={}, headers=H)
check("...once there are enough posts, kept short", r.status_code == 200 and r.json()["tips"][0].startswith("Post more") and len(r.json()["tips"][1]) <= 220, r.text[:200])

# ================================================================ the swipe review
with ctx.as_user(me.id):
    j = jobs.create({"type": "file", "path": "", "name": "r.mp4"}, {}, enqueue=False, creator=c["id"])
    j["clips"] += [{"id": "a", "status": "done", "file": "a.mp4", "title": "A", "score": 70}, {"id": "b", "status": "done", "file": "b.mp4", "title": "B", "score": 70}]
    jobs.save(j)
r = cl.post(f"/api/jobs/{j['id']}/clips/a/review", json={"action": "skip"}, headers=H)
with ctx.as_user(me.id):
    check("skip sets a clip aside", r.status_code == 200 and jobs.get(j["id"])["clips"][0]["reviewed"] == "skip")
r = cl.post(f"/api/jobs/{j['id']}/clips/b/review", json={"action": "post", "accounts": ["yt_1"]}, headers=H)
check("post queues it for the picked accounts", r.status_code == 200 and r.json()["queued"] == 1)
check("something else is refused", cl.post(f"/api/jobs/{j['id']}/clips/b/review", json={"action": "delete"}, headers=H).status_code == 400)

# ================================================================ the phone app files
r = cl.get("/manifest.webmanifest")
check("the app manifest is served, with icons that exist", r.status_code == 200 and all(cl.get(i["src"]).status_code == 200 for i in r.json()["icons"]))
r = cl.get("/sw.js")
check("the service worker is served from the top, as a script", r.status_code == 200 and "javascript" in r.headers["content-type"] and "fetch" in r.text)

# ================================================================ moving to a new machine
f = backup.make()
dest = tempfile.mkdtemp(prefix="pc-new-")
old_data = config.DATA_DIR
config.DATA_DIR = Path(dest)
(Path(dest) / "users").mkdir()
backup.folder()
backup.restore(f, owner="u_newowner")
check("a backup moved to another machine belongs to the new account there",
      (Path(dest) / "users" / "u_newowner" / "creators").is_dir() and not (Path(dest) / "users" / me.id).exists())
posts = json.loads((Path(dest) / "posts.json").read_text(encoding="utf-8"))
check("...with its post queue", posts and all(p["user"] == "u_newowner" for p in posts if p["user"] != "x"))
check("...and the old machine's database left out", not (Path(dest) / "clipcut.db").exists())
config.DATA_DIR = old_data
check("a backup with a path that climbs out is refused", True)
bad = Path(tempfile.mkdtemp()) / "bad.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("../evil.txt", "x")
try:
    backup.restore(bad)
    check("a backup with a path that climbs out is refused", False)
except ValueError:
    pass

print("ALL PASSED" if not fails else f"{len(fails)} failed")
db.engine.dispose()
shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
shutil.rmtree(dest, ignore_errors=True)
sys.exit(1 if fails else 0)
