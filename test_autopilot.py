"""Autopilot: new uploads clipped by themselves, the logo and credit on clips, Telegram buttons, keyword DMs on
Instagram, best posting times, a second title on YouTube, posting hits again, Reel covers and Stories, and the
weekly report. Platforms, Telegram and the AI are stand-ins; nothing leaves this machine."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-autopilot-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="0", CLIPCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import (accounts, auth, autofetch, config, creators, ctx, db, growth, jobs, posting, render,  # noqa: E402
                    replies, server, telebot)

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


class R:
    def __init__(self, code, data):
        self.status_code, self._d, self.text = code, data, json.dumps(data)

    def json(self):
        return self._d


me = auth.local_user()
cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
H = {"Origin": "http://127.0.0.1:8765"}

# ================================================================ new uploads, clipped by themselves
feed = {"https://www.youtube.com/@pro/videos": [{"id": "old1", "url": "https://www.youtube.com/watch?v=old1", "title": "Old", "duration": 900, "live": False}],
        "https://www.youtube.com/@pro/streams": []}
autofetch.list_feed = lambda url, n=10: list(feed.get(url, []))
made_jobs = []
real_create = jobs.create


def fake_create(source, options, enqueue=True, creator=None, kind="video"):
    j = real_create(source, options, enqueue=False, creator=creator, kind=kind)
    made_jobs.append(j)
    return j


autofetch.jobs.create = fake_create
with ctx.as_user(me.id):
    c = creators.create({"name": "Pro", "channels": {"youtube": "https://www.youtube.com/@pro"}})
    check("a YouTube channel is read from its videos and its past streams", autofetch.feeds(c) == ["https://www.youtube.com/@pro/videos", "https://www.youtube.com/@pro/streams"])
    check("a Twitch channel from its past broadcasts", autofetch.feeds({"channels": {"twitch": "https://www.twitch.tv/pro"}}) == ["https://www.twitch.tv/pro/videos?filter=archives&sort=time"])
r = cl.put(f"/api/creators/{c['id']}", json={"auto_uploads": True, "uploads_max_min": 60}, headers=H)
check("new uploads can be switched on", r.status_code == 200 and r.json()["auto_uploads"] is True, r.text)
for _ in range(50):
    with ctx.as_user(me.id):
        if autofetch.status(c["id"])["since"]:
            break
    time.sleep(0.1)
with ctx.as_user(me.id):
    c = creators.get(c["id"])
    check("what was already on the channel is left alone", autofetch.check_creator(c) == 0 and not made_jobs)
    feed["https://www.youtube.com/@pro/videos"] = [
        {"id": "new1", "url": "https://www.youtube.com/watch?v=new1", "title": "Ranked grind", "duration": 1800, "live": False},
        {"id": "long1", "url": "https://www.youtube.com/watch?v=long1", "title": "8 hour stream", "duration": 8 * 3600, "live": False},
        {"id": "live1", "url": "https://www.youtube.com/watch?v=live1", "title": "LIVE now", "duration": 0, "live": True}] + feed["https://www.youtube.com/@pro/videos"]
    added = autofetch.check_creator(c)
    check("a new upload becomes a video of that creator", added == 1 and made_jobs[0]["creator"] == c["id"] and made_jobs[0]["source"]["url"].endswith("new1"))
    check("an upload longer than the limit is skipped", not any(j["source"]["url"].endswith("long1") for j in made_jobs))
    check("a stream still live is left for later", "live1" not in autofetch._state(c["id"])["seen"])
    check("nothing is clipped twice", autofetch.check_creator(c) == 0)

# ================================================================ the logo and the credit line
png = io.BytesIO()
from PIL import Image  # noqa: E402
Image.new("RGBA", (300, 120), (255, 140, 50, 255)).save(png, "PNG")
r = cl.post(f"/api/creators/{c['id']}/logo", files={"file": ("logo.txt", b"not a picture", "text/plain")}, headers=H)
check("a file that is not a picture is refused as a logo", r.status_code == 400, r.text)
r = cl.post(f"/api/creators/{c['id']}/logo", files={"file": ("logo.png", png.getvalue(), "image/png")}, headers=H)
check("a logo can be added", r.status_code == 200 and cl.get(f"/api/creators/{c['id']}/logo").status_code == 200, r.text)
cl.put(f"/api/creators/{c['id']}", json={"brand_on": True, "credit_text": "🎮 Clip: @pro", "brand_pos": "zz"}, headers=H)
with ctx.as_user(me.id):
    c = creators.get(c["id"])
    b = jobs._brand({"creator": c["id"]})
check("an unknown corner means top left", c["brand_pos"] == "tl")
check("clips of that creator carry the logo and the credit", b["logo"].endswith("logo.png") and b["credit"] == "🎮 Clip: @pro")
style, ev = render.brand_ass(b["credit"], 10, render.brand_layout("tl", (300, 120)))
check("the credit is drawn without the emoji the fonts lack", "Clip: @pro" in ev and "🎮" not in ev and style.startswith("Style: Credit"))
check("the logo sits in its corner, the text under it", render.brand_layout("tl", (300, 120))["logo"] == (36, 36, 150, 60)
      and render.brand_layout("tl", (300, 120))["text"] == (36, 106))
work = Path(tempfile.mkdtemp())
src = work / "src.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-f", "lavfi", "-i",
                "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
render.install_fonts()
out = render.render_clip(src, work / "out", "c1", {"start": 0.2, "end": 2.2, "hook": "WOW", "brand": b}, [], 640, 360)
check("a clip with a logo and credit is made", (work / "out" / "c1.mp4").stat().st_size > 1000 and out["file"] == "c1.mp4")

# ================================================================ Telegram buttons
tg = []


def tpost(url, data=None, files=None, timeout=None, json=None, params=None, headers=None):
    tg.append((url.rsplit("/", 1)[1], data))
    return R(200, {"ok": True, "result": {}})


updates = []


def tget(url, params=None, timeout=None, headers=None):
    return R(200, {"ok": True, "result": [u for u in updates if u["update_id"] >= int(params.get("offset", 0))]})


telebot.httpx.post, telebot.httpx.get = tpost, tget
with ctx.as_user(me.id):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "GameXtra", "added": time.time(), "access_token": "a", "refresh_token": "r", "expires": time.time() + 3600})
    accounts._put({"id": "ig_1", "platform": "instagram", "name": "@gamextra00", "added": time.time(), "user_id": "17", "token": "t", "token_time": time.time()})
    accounts.save_settings({"telegram_token": "123:abc", "telegram_chat": "999", "tg_control": True})
    creators.update(c["id"], {"accounts": ["yt_1"]})
    job = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c["id"])
    clip = {"id": "k1", "status": "done", "file": "k1.mp4", "title": "Clutch 🔥", "description": "Wait 😱", "hashtags": ["gaming"], "score": 88}
    job["clips"].append(clip)
    jobs.save(job)
    telebot.offer_clip(job, clip)
    kb = json.loads(tg[-1][1]["reply_markup"])["inline_keyboard"]
    check("a new clip arrives on Telegram with Post now, Add to queue and Skip",
          tg[-1][0] == "sendMessage" and [b["text"] for row in kb for b in row] == ["🚀 Post now", "🕒 Add to queue", "🗑 Skip"])
    queue_key = kb[0][1]["callback_data"]
    telebot.handle({"update_id": 1, "callback_query": {"id": "q", "data": queue_key, "message": {"message_id": 5, "chat": {"id": 12345}}}})
    check("a button pressed in someone else's chat does nothing", not posting._mine())
    telebot.handle({"update_id": 2, "callback_query": {"id": "q", "data": queue_key, "message": {"message_id": 5, "chat": {"id": 999}}}})
    check("Add to queue queues the clip", len(posting._mine()) == 1 and posting._mine()[0]["clip"] == "k1")
    answer = [d for m, d in tg if m == "answerCallbackQuery"][-1]["text"]
    check("...and Telegram says when it goes out", answer.startswith("Queued for"), answer)
    telebot.handle({"update_id": 3, "callback_query": {"id": "q", "data": queue_key, "message": {"message_id": 5, "chat": {"id": 999}}}})
    check("a button works once", len(posting._mine()) == 1 and [d for m, d in tg if m == "answerCallbackQuery"][-1]["text"] == "This button was already used.")
    telebot.handle({"update_id": 4, "message": {"chat": {"id": 999}, "text": "/pause"}})
    check("/pause pauses all posting", accounts.settings()["paused"] is True)
    telebot.handle({"update_id": 5, "message": {"chat": {"id": 999}, "text": "/resume"}})
    check("/resume starts it again", accounts.settings()["paused"] is False)
    telebot.handle({"update_id": 6, "message": {"chat": {"id": 1}, "text": "/pause"}})
    check("commands from another chat are ignored", accounts.settings()["paused"] is False)
    updates[:] = [{"update_id": 40, "message": {"chat": {"id": 999}, "text": "/status"}}]
    telebot.poll_once()
    check("the bot reads new messages and answers /status", any(m == "sendMessage" and "summary" in d.get("text", "") for m, d in tg))
    check("...and remembers where it got to", telebot._state()["offset"] == 41)

# ================================================================ keyword DMs on Instagram
dms = []


def rget(url, params=None, headers=None, timeout=None):
    if url.endswith("/m1/comments"):
        return R(200, {"data": [{"id": "c1", "text": "which GAME is this?", "username": "fan"}, {"id": "c2", "text": "nice", "username": "fan2"}]})
    return R(200, {"items": [], "data": []})


def rpost(url, params=None, json=None, data=None, headers=None, timeout=None):
    dms.append((url, json))
    return R(200, {"message_id": "m"})


replies.httpx.get, replies.httpx.post = rget, rpost
with ctx.as_user(me.id):
    posting._posts.append({"id": "pm", "user": me.id, "job": job["id"], "clip": "k1", "creator": c["id"], "account": "ig_1",
                           "account_name": "@gamextra00", "platform": "instagram", "status": "posted", "due_at": time.time() - 99,
                           "posted_at": time.time() - 99, "title": "Clutch", "remote_id": "m1", "url": "", "tries": 0, "views": None})
    accounts.save_settings({"reply_mode": "off", "dm_rules": [{"word": "game", "text": "It's Valorant! Full stream on YouTube 🎮"}, {"word": "", "text": "x"}]})
    check("an empty keyword is dropped", len(accounts.settings()["dm_rules"]) == 1)
    replies.check()
    check("a comment with the keyword gets the DM, even with replies off",
          len(dms) == 1 and dms[0][0].endswith("/17/messages") and dms[0][1] == {"recipient": {"comment_id": "c1"}, "message": {"text": "It's Valorant! Full stream on YouTube 🎮"}}, str(dms))
    replies.check()
    check("...once only", len(dms) == 1)
    check("the DM shows in Comments", any(i.get("kind") == "dm" and i["status"] == "sent" for i in replies.listing()["items"]))

# ================================================================ best times, second title, hits again, weekly report
with ctx.as_user(me.id):
    posting._posts[:] = [p for p in posting._posts if p["user"] != me.id]
    base = time.mktime(time.strptime("2026-10-01 00:00", "%Y-%m-%d %H:%M"))
    hours = [19, 19, 19, 13, 13, 9, 9, 22, 22, 2]
    views = [5000, 4000, 6000, 3000, 2800, 100, 120, 900, 1100, 50]
    for i, (h, v) in enumerate(zip(hours, views)):
        t = time.time() - (3 + i) * 86400
        lt = time.localtime(t)
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, 5, 0, 0, 0, -1))
        posting._posts.append({"id": f"h{i}", "user": me.id, "job": job["id"], "clip": "k1", "creator": c["id"], "account": "yt_1",
                               "account_name": "GameXtra", "platform": "youtube", "status": "posted", "due_at": t, "posted_at": t,
                               "created": t, "title": f"Clip {i}", "remote_id": f"v{i}", "url": "", "tries": 0, "views": v})
    b = growth.best_hours(["yt_1"])
    check("the best hour to post comes from your own views", b["enough"] and b["hours"][0]["hour"] == 19, str(b["hours"][:3]))
    creators.update(c["id"], {"daily_cap": 3, "auto_times": True})
    check("posting times are suggested from the best hours, spread apart", growth.suggest_times(creators.get(c["id"])) == "13:00, 19:00, 22:00",
          growth.suggest_times(creators.get(c["id"])))
    growth._auto_times()
    check("...and set by themselves when switched on", creators.get(c["id"])["post_times"] == "13:00, 19:00, 22:00")

    retitled = []
    growth.new_text = lambda title, desc, why: {"title": "He did NOT expect that 😱", "description": "New caption 🔥"}
    growth.youtube_retitle = lambda acc, vid, t: retitled.append((vid, t))
    slow = time.time() - 4 * 3600
    posting._posts.append({"id": "slow", "user": me.id, "job": job["id"], "clip": "k1", "creator": c["id"], "account": "yt_1",
                           "account_name": "GameXtra", "platform": "youtube", "status": "posted", "due_at": slow, "posted_at": slow,
                           "created": slow, "title": "Boring title", "remote_id": "vslow", "url": "", "tries": 0, "views": 40})
    growth._ab_titles()
    check("a slow Short is left alone unless the creator wants second titles", not retitled)
    creators.update(c["id"], {"ab_titles": True})
    growth._ab_titles()
    p = next(x for x in posting._mine() if x["id"] == "slow")
    check("a slow Short gets a second title, once", retitled == [("vslow", "He did NOT expect that 😱")] and p["ab_old"] == "Boring title")
    growth._ab_titles()
    check("...only once", len(retitled) == 1)

    creators.update(c["id"], {"recycle": True, "recycle_after_days": 7})
    old = time.time() - 30 * 86400
    posting._posts.append({"id": "hit", "user": me.id, "job": job["id"], "clip": "k1", "creator": c["id"], "account": "yt_1",
                           "account_name": "GameXtra", "platform": "youtube", "status": "posted", "due_at": old, "posted_at": old,
                           "created": old, "title": "Hit", "remote_id": "vhit", "url": "", "tries": 0, "views": 90000})
    config_ai = config.ai_ready
    config.ai_ready = lambda: True
    growth._recycle()
    again = [x for x in posting._mine() if x.get("recycle_of") == "hit"]
    check("a hit is posted again, with new text", len(again) == 1 and again[0]["title_override"] == "He did NOT expect that 😱" and again[0]["status"] == "scheduled")
    growth._recycle()
    check("...one a day at most", len([x for x in posting._mine() if x.get("recycle_of")]) == 1)
    config.ai_ready = config_ai
    w = growth.weekly_text()
    check("the weekly report has posts, views and the top clip", "weekly report" in w and "Views:" in w and "Top clip" in w, w)

# ================================================================ Reel cover and Story
sent = []


def apost(url, data=None, json=None, headers=None, params=None, timeout=None, content=None):
    sent.append((url, data))
    if url.endswith("/media"):
        return R(200, {"id": "box"})
    return R(200, {"id": "pub"})


accounts.httpx.post = apost
accounts.httpx.get = lambda url, params=None, headers=None, timeout=None: R(200, {"status_code": "FINISHED", "permalink": "https://i/x"})
with ctx.as_user(me.id):
    jd = jobs.job_dir(job["id"]) / "clips"
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "k1.mp4").write_bytes(b"\0" * 100)
    accounts.instagram_upload(accounts.get("ig_1"), jd / "k1.mp4", "cap", job["id"])
    reel = next(d for u, d in sent if u.endswith("/media"))
    check("a Reel uses the cover moment as its grid picture", reel["media_type"] == "REELS" and reel["thumb_offset"] == "1200")
    sent.clear()
    accounts.instagram_upload(accounts.get("ig_1"), jd / "k1.mp4", "", job["id"], kind="STORIES")
    story = next(d for u, d in sent if u.endswith("/media"))
    check("a Story is posted without a caption", story["media_type"] == "STORIES" and "caption" not in story)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402
db.engine.dispose()
shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
