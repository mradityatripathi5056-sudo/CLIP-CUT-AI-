"""The latest additions: email codes (checking the owner's email, two-step sign-in), quick add of a YouTube channel
with a daily plan, India/worldwide audience, page language, Instagram Collab, Threads/Bluesky/Discord, music,
reaction sticker, song check, best length, permission, affiliate links, link-in-bio page, sponsors, YouTube
monetization progress, phone push and team roles. Nothing outside this machine is contacted."""
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-aud-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="1", CLIPCUT_PUBLIC_URL="https://clips.example.com",
                  CLIPCUT_VERIFY_EMAIL="0", CLIPCUT_SMTP_HOST="")
sys.path.insert(0, ".")
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio import (accounts, affiliate, auth, brain, config, creators, ctx, db, growth, mailer, mailsetup, musiclib,  # noqa: E402
                    permission, posting, quickadd, server, sponsors, team, usage, webpush, ytmoney)

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


BASE = "https://clips.example.com"
H = {"Origin": BASE}
sent = []
mailer.send = lambda to, subject, *a, **k: sent.append((to, subject)) or True   # noqa: E731


def person(email, pw=None):
    import hashlib  # noqa: F401
    u, _ = auth._create(email, email.split("@")[0], password_hash=auth.hash_password(pw) if pw else "x")
    cl = TestClient(server.app, base_url=BASE, follow_redirects=False)
    cl.cookies.set(auth.COOKIE, auth.start_session(u.id))
    return u, cl


# ---------------------------------------------------------------- email setup and codes
owner, a = person("aditya@example.com", "Very-strong-pw-1")
with ctx.as_user(owner.id):
    try:
        mailsetup.save("smtp.gmail.com", 587, "bad", "abcdefghijklmnop")
        check("a wrong sender email is refused", False)
    except ValueError:
        check("a wrong sender email is refused", True)
    pub = mailsetup.save("smtp.gmail.com", 587, "gamextra00@gmail.com", "abcd efgh ijkl mnop")
check("email details are saved and used", pub["ready"] and config.SMTP_HOST == "smtp.gmail.com" and config.smtp_password() == "abcdefghijklmnopq"[:16])
check("the app password is never sent back", "password" not in pub and pub["has_password"])
check("the saved file is only readable by this user", oct(os.stat(config.DATA_DIR / "smtp.json").st_mode)[-3:] == "600")
t = mailsetup.send_code("aditya@example.com", "sign in", {"uid": "x"})
code = sent[-1][1].split()[-1]
check("a 6-digit code is emailed", code.isdigit() and len(code) == 6)
try:
    mailsetup.check_code(t, "000000" if code != "000000" else "111111", "sign in")
    check("a wrong code is refused", False)
except ValueError:
    check("a wrong code is refused", True)
check("the right code works", mailsetup.check_code(t, code, "sign in") == {"uid": "x"})
try:
    mailsetup.check_code(t, code, "sign in")
    check("a code works only once", False)
except ValueError:
    check("a code works only once", True)
t2 = mailsetup.send_code("a@example.com", "sign in", {})
c2 = sent[-1][1].split()[-1]
for _ in range(5):
    try:
        mailsetup.check_code(t2, "999999" if c2 != "999999" else "888888", "sign in")
    except ValueError:
        pass
try:
    mailsetup.check_code(t2, c2, "sign in")
    check("after 5 wrong tries even the right code is refused", False)
except ValueError:
    check("after 5 wrong tries even the right code is refused", True)
check("emails are masked on screen", mailsetup.mask("aditya@example.com") == "ad••••@example.com")

# two-step sign-in through the API
anon = TestClient(server.app, base_url=BASE, follow_redirects=False)
with ctx.as_user(owner.id):
    accounts.save_settings({"two_step": True})
r = anon.post("/api/auth/login", json={"email": "aditya@example.com", "password": "Very-strong-pw-1"}, headers=H)
check("with two-step on, the password alone doesn't sign in", r.status_code == 200 and r.json().get("two_step") and auth.COOKIE not in r.cookies, r.text)
code = sent[-1][1].split()[-1]
r2 = anon.post("/api/auth/code", json={"ticket": r.json()["ticket"], "code": "12"}, headers=H)
check("a wrong code at sign-in is refused", r2.status_code == 400)
r2 = anon.post("/api/auth/code", json={"ticket": r.json()["ticket"], "code": code}, headers=H)
check("the emailed code signs in", r2.status_code == 200 and r2.json()["user"]["email"] == "aditya@example.com", r2.text)
check("a wrong password never gets a code", anon.post("/api/auth/login", json={"email": "aditya@example.com", "password": "nope-nope-1"}, headers=H).status_code == 400)
with ctx.as_user(owner.id):
    accounts.save_settings({"two_step": False})

# ---------------------------------------------------------------- audience and Hinglish
with ctx.as_user(owner.id):
    c_in = creators.create({"name": "Desi Gamer", "audience": "india"})
    c_gl = creators.create({"name": "World Gamer", "audience": "global"})
    check("audience is kept; anything else falls back to India", creators.create({"name": "X", "audience": "mars"})["audience"] == "india")
    usage._where.creator = c_in["id"]
    rules_in = brain._game_rules("")
    usage._where.creator = c_gl["id"]
    rules_gl = brain._game_rules("")
    usage._where.creator = None
    check("India clips are written in Hinglish, never in Devanagari", "Hinglish" in rules_in and "Devanagari" in rules_in)
    check("worldwide clips are written in English, not Hinglish", "English" in rules_gl and "Hinglish" not in rules_gl)
    try:
        creators.update(c_in["id"], {"ig_collab": "bad name!"})
        check("a wrong collab username is refused", False)
    except ValueError:
        check("a wrong collab username is refused", True)
    check("collab usernames are cleaned and kept to 3", creators.update(c_in["id"], {"ig_collab": "@One, two three four"})["ig_collab"] == "one, two, three")
    try:
        creators.update(c_in["id"], {"affiliate": "Mouse | javascript:alert(1)"})
        check("a link that isn't https is refused", False)
    except ValueError:
        check("a link that isn't https is refused", True)
    c_in = creators.update(c_in["id"], {"affiliate": "My mouse | https://amzn.to/abc\nTop-up | https://shop.example.com/x"})

# ---------------------------------------------------------------- quick add
check("India plan: lunch, evening, night", quickadd.plan("india", 3)["times_india"] == ["12:30", "15:30", "18:30"])
check("worldwide plan follows US and Europe evenings", quickadd.plan("global", 3)["times_india"] == ["06:30", "08:30", "20:00"])
check("busy channels get more Reels a day, never more than 5",
      quickadd.per_day([{"duration": 7200}] * 8) == 5 and quickadd.per_day([{"duration": 600}] * 5) == 3 and quickadd.per_day([]) == 3)
r = a.post("/api/quick-add", json={"url": "https://evil.example/x"}, headers=H)
check("only channel links are taken", r.status_code == 400)
import studio.autofetch as af  # noqa: E402
af.list_feed = lambda url, n=10: [{"id": str(i), "url": "u", "title": "t", "duration": 5400, "live": False} for i in range(4)]
af.turned_on = lambda cid: None
r = a.post("/api/quick-add", json={"url": "https://www.youtube.com/@TotalGaming093/videos", "audience": "india"}, headers=H)
d = r.json() if r.status_code == 200 else {}
check("quick add makes the creator with a daily plan", r.status_code == 200 and d["plan"]["per_day"] == 4 and d["creator"]["daily_cap"] == 4
      and d["creator"]["auto_uploads"] and d["creator"]["audience"] == "india" and d["creator"]["name"] == "TotalGaming093", r.text)
check("...posting at the planned times", d.get("creator", {}).get("post_times", "").count(":") == 4)
check("the same channel can't be added twice", a.post("/api/quick-add", json={"url": "https://www.youtube.com/@TotalGaming093"}, headers=H).status_code == 400)

# ---------------------------------------------------------------- posting extras
check("a page set to English gets English for Hinglish clips", posting._wants_english({"lang": "english"}, {"audience": "india"}))
check("auto pages follow the creator", not posting._wants_english({"lang": "auto"}, {"audience": "india"}))
check("Bluesky text stays under 300", len(posting.short_text("T" * 250, "#a #bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb #c", 300)) <= 300)
with ctx.as_user(owner.id):
    blk = posting.affiliate_block(c_in)
    check("links go through counted short links", "/go/" in blk and "My mouse" in blk and "amzn" not in blk, blk)
    code_ = blk.split("/go/")[1].split()[0]
check("a click is counted and goes to the real link", affiliate.click(code_) == "https://amzn.to/abc")
check("unknown codes go nowhere", affiliate.click("zzz") is None and anon.get("/go/123456789").status_code == 404)
r = anon.get("/go/" + code_)
check("/go/ redirects without being signed in", r.status_code == 302 and r.headers["location"] == "https://amzn.to/abc")
with ctx.as_user(owner.id):
    st = affiliate.stats()
    check("clicks show on the Money page", any(x["clicks"] == 2 for x in st), st)

# ---------------------------------------------------------------- link-in-bio
with ctx.as_user(owner.id):
    try:
        affiliate.set_bio("a b", "", "")
        check("a page name with spaces is refused", False)
    except ValueError:
        check("a page name with spaces is refused", True)
    affiliate.set_bio("gamextra", "GameXtra <b>", "Daily edits")
other, o = person("other@example.com")
with ctx.as_user(other.id):
    try:
        affiliate.set_bio("gamextra", "", "")
        check("someone else can't take your page name", False)
    except ValueError:
        check("someone else can't take your page name", True)
r = anon.get("/c/gamextra")
check("the bio page is public and escapes text", r.status_code == 200 and "GameXtra &lt;b&gt;" in r.text and "My mouse" in r.text, r.text[:200])
check("unknown pages are not found", anon.get("/c/nobody-here").status_code == 404)

# ---------------------------------------------------------------- sponsors
with ctx.as_user(owner.id):
    sponsors.save({"brand": "Krafton", "amount": 5000, "due": time.strftime("%Y-%m-%d"), "status": "agreed"})
    row = sponsors.save({"brand": "Boat", "amount": "2500", "status": "paid"})
    L = sponsors.listing()
    check("deals add up by status", L["totals"]["paid"] == 2500 and L["totals"]["agreed"] == 5000)
    check("deals due this week are flagged", [x["brand"] for x in L["due_soon"]] == ["Krafton"])
    try:
        sponsors.save({"brand": "", "amount": 1})
        check("a deal needs a brand", False)
    except ValueError:
        check("a deal needs a brand", True)
check("another person can't see your deals", o.get("/api/sponsors").json()["deals"] == [])

# ---------------------------------------------------------------- permission
with ctx.as_user(owner.id):
    msg = permission.message({"name": "Mortal", "audience": "india"}, "gameXtra00")
    check("the ask message names the streamer and your page, in Hinglish for India", "Mortal" in msg and "gameXtra00" in msg and "bhai" in msg)
    check("...and in English for others", "Would you be OK" in permission.message({"name": "Ninja", "audience": "global"}, "p"))
    held = creators.update(c_gl["id"], {"only_with_permission": True, "autopost": True, "accounts": [], "permission": "asked"})
    posting.enqueue_calls = []
    real = posting.enqueue
    posting.enqueue = lambda *a_, **k: posting.enqueue_calls.append(a_) or [1]
    creators.update(c_gl["id"], {"accounts": ["acc1"]}) if False else None
    c_ = creators.get(c_gl["id"]); c_["accounts"] = ["x"]
    creators._write(c_)
    posting.on_clip_ready({"creator": c_gl["id"]}, {"score": 99, "title": "t"})
    check("no permission yet: the clip isn't posted by itself", posting.enqueue_calls == [])
    creators.update(c_gl["id"], {"permission": "allowed"})
    posting.on_clip_ready({"creator": c_gl["id"]}, {"score": 99, "title": "t"})
    check("once allowed it is", len(posting.enqueue_calls) == 1)
    posting.enqueue = real

# ---------------------------------------------------------------- music and the sticker
with ctx.as_user(owner.id):
    import subprocess
    wav = Path(tempfile.mkdtemp()) / "beat.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=3", str(wav)], check=True)
    musiclib.add("hype", "My Beat!!.wav", wav.read_bytes())
    check("tracks are added under a safe name", musiclib.listing()["hype"] == ["My Beat.wav"])
    try:
        musiclib.add("hype", "x.exe", b"MZ")
        check("only audio files are taken", False)
    except ValueError:
        check("only audio files are taken", True)
    tr = musiclib.pick(str(musiclib.folder()), "fail")
    check("a fail without funny tracks falls back to any mood", tr is not None and tr.name == "My Beat.wav")
    bed = musiclib.bed(tr, 7.0, 48000)
    check("the music is looped to the clip and kept quiet", len(bed) == int(48000 * 7.5) and float(np.max(np.abs(bed))) <= 0.101)

# a real render with music and the sticker
from PIL import Image  # noqa: E402

from studio import fx, render  # noqa: E402
work = Path(tempfile.mkdtemp())
src = work / "src.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=8", "-f", "lavfi", "-i",
                "sine=f=440:d=8", "-af", "volume='if(between(t,4,4.5),1,0.05)':eval=frame", "-shortest", "-c:v", "libx264",
                "-preset", "ultrafast", str(src)], check=True)
st = work / "react.png"
Image.new("RGBA", (300, 300), (255, 0, 0, 200)).save(st)
render.install_fonts() if hasattr(render, "install_fonts") else None
with ctx.as_user(owner.id):
    clip = {"start": 0.0, "end": 8.0, "hook": "kya clutch", "title": "t", "category": "clutch", "layout": "blur",
            "fx": {"music": str(musiclib.folder()), "reaction": str(st)}}
    plan = render._fx_plan(clip, src, 0.0, 8.0, [], work, 900)
check("the plan has the music and the sticker on the loud moment", plan.get("music") == "My Beat.wav" and plan.get("reaction")
      and 3.0 <= plan["reaction"][0] <= 4.6, plan)
out = work / "out"
try:
    res = render.render_clip(src, out, "c1", clip, [], 1280, 720)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out / "c1.mp4")],
                           capture_output=True, text=True).stdout
    check("the clip renders with music and the sticker", abs(float(probe) - 8.0) < 0.5, probe)
except Exception as e:  # noqa: BLE001
    check("the clip renders with music and the sticker", False, str(e)[:300])

# ---------------------------------------------------------------- best length
with ctx.as_user(owner.id):
    import studio.jobs as jobs  # noqa: E402
    fake_jobs = [{"id": "j1", "creator": c_in["id"], "clips": [{"id": f"k{i}", "start": 0, "end": 20 if i < 5 else 50} for i in range(10)]}]
    jobs.list_jobs = lambda: fake_jobs
    growth._posted = lambda account_ids=None, days=60: [{"job": "j1", "clip": f"k{i}", "creator": c_in["id"], "views": 9000 if i < 5 else 900,
                                                       "posted_at": time.time()} for i in range(10)]
    b = growth.best_length(c_in["id"])
    check("short clips with more views win", b["enough"] and b["lengths"][0]["from"] == 15)
    creators.update(c_in["id"], {"auto_length": True})
    growth._auto_length()
    c2_ = creators.get(c_in["id"])
    check("the creator's lengths follow", (c2_["min_len"], c2_["max_len"]) == (15, 25))

# ---------------------------------------------------------------- YouTube monetization
p = ytmoney.progress(600, 1200, 4_000_000, 3, "fan")
check("500 subs + 3M Shorts views: fan funding is open", p["ok"] and p["percent"] == 100)
p = ytmoney.progress(600, 1200, 4_000_000, 3, "ads")
check("...but not ads yet (needs 1,000 subs)", not p["ok"] and p["percent"] == 40)
check("the 2027 rules need double the hours or Shorts views", ytmoney.TIERS["ads_2027"]["hours"] == 8000 and ytmoney.TIERS["ads_2027"]["shorts_90d"] == 20_000_000)

# ---------------------------------------------------------------- Threads/Bluesky/Discord and page language
import httpx  # noqa: E402


class R:
    def __init__(self, code=200, data=None):
        self.status_code, self._d, self.text = code, data or {}, str(data)

    def json(self):
        return self._d


calls = []
httpx.get = lambda url, **k: calls.append(url) or R(200, {"name": "clips", "id": "1", "username": "gx"})
httpx.post = lambda url, **k: calls.append(url) or R(200, {"handle": "gx.bsky.social", "did": "did:plc:1", "accessJwt": "j"})
with ctx.as_user(owner.id):
    try:
        accounts.connect_key("discord", {"webhook": "https://evil.example/hook"})
        check("only Discord webhook links are taken", False)
    except ValueError:
        check("only Discord webhook links are taken", True)
    d1 = accounts.connect_key("discord", {"webhook": "https://discord.com/api/webhooks/123/abc-DEF"})
    d2 = accounts.connect_key("bluesky", {"handle": "@gx.bsky.social", "password": "abcd-efgh-ijkl"})
    d3 = accounts.connect_key("threads", {"token": "T" * 40})
    names = {x["platform"]: x["name"] for x in accounts.list_accounts()}
    check("Discord, Bluesky and Threads connect with a key", names == {"discord": "#clips", "bluesky": "@gx.bsky.social", "threads": "@gx"}, names)
    check("their keys are never listed", all("token" not in x and "webhook" not in x and "app_password" not in x for x in accounts.list_accounts()))
    accounts.set_lang(d1["id"], "english")
    check("a page can be set to always post English", accounts.get(d1["id"])["lang"] == "english")
r = a.post("/api/accounts/key/tiktok", json={}, headers=H)
check("other platforms can't be added by key", r.status_code == 404)

# ---------------------------------------------------------------- phone push
with ctx.as_user(owner.id):
    k = webpush.public_key()
    check("a push key is made once", len(k) > 80 and webpush.public_key() == k)
    try:
        webpush.add({"endpoint": "http://x", "keys": {}})
        check("a bad push address is refused", False)
    except ValueError:
        check("a bad push address is refused", True)
    webpush.add({"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "x", "auth": "y"}})
    webpush.add({"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "x", "auth": "y"}})
    check("the same phone is kept once", len(webpush.subs()) == 1)

# ---------------------------------------------------------------- team roles
ed, e = person("editor@example.com")
a.post("/api/team", json={"email": "editor@example.com", "role": "editor"}, headers=H)
check("the teammate is an editor", team.role_of(auth.get_user(ed.id)) == "editor")
check("an editor sees the creators", e.get("/api/creators").status_code == 200 and len(e.get("/api/creators").json()) >= 2)
check("an editor can't change a creator", e.put(f"/api/creators/{c_in['id']}", json={"daily_cap": 9}, headers=H).status_code == 403)
check("an editor can't change settings", e.put("/api/settings", json={"paused": True}, headers=H).status_code == 403)
check("an editor can't see the money", e.get("/api/sponsors").status_code == 403)
check("an editor can't use the Manager", e.get("/api/manager").status_code == 403)
check("an editor can still see the calendar", e.get(f"/api/calendar?start={int(time.time())}&end={int(time.time()) + 86400 * 30}").status_code == 200)
r = a.put("/api/team/editor@example.com/role", json={"role": "manager"}, headers=H)
check("the owner can make them a manager", r.status_code == 200 and team.role_of(auth.get_user(ed.id)) == "manager")
check("...who then can change a creator", e.put(f"/api/creators/{c_in['id']}", json={"daily_cap": 9}, headers=H).status_code == 200)

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
