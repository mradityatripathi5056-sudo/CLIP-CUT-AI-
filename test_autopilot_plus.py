"""Autopilot: learning a page's style, hook tests, the smart queue, the viral booster, fast live mode, series,
the reach-drop alarm, the copyright guard, the duplicate guard, the slot filler, the streamer finder, competitors,
English-subtitle versions, the best cover frame, hook formats and the Telegram channel. Nothing outside this
machine is contacted."""
import os
import subprocess
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-ap-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="", CLIPCUT_PUBLIC_URL="https://clips.example.com")
sys.path.insert(0, ".")
from pathlib import Path  # noqa: E402

from studio import accounts, alerts, autopilot, brain, creators, ctx, db, growth, jobs, posting, usage  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


alerts.notify = lambda *a, **k: None          # noqa: E731
UID = "owner_test1"
work = Path(tempfile.mkdtemp())


def make_video(path, color="red", tone=440, loud_at=None, d=8):
    af = f"volume='if(between(t,{loud_at},{loud_at + 0.5}),1,0.05)':eval=frame" if loud_at is not None else "volume=0.3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=360x640:d={d}" if color == "test" else f"color=c={color}:s=360x640:d={d}",
                    "-f", "lavfi", "-i", f"sine=f={tone}:d={d}", "-af", af, "-shortest", "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)


with ctx.as_user(UID):
    for i, (pf, name) in enumerate([("youtube", "GameXtra YT"), ("instagram", "@gamextra00"), ("facebook", "GameXtra FB")]):
        accounts._put({"id": f"a{i}", "platform": pf, "name": name, "added": time.time(), "token": "t", "refresh": "r",
                       "expires": time.time() + 9999, "uid": "1"})
    c = creators.create({"name": "Mortal", "accounts": ["a0", "a1", "a2"], "autopost": True, "audience": "india"})
    cid = c["id"]
    d = creators.root(cid) / "videos" / "j1"
    (d / "clips").mkdir(parents=True)
    clips = []
    for i in range(12):
        f = d / "clips" / f"k{i}.mp4"
        make_video(f, color=["red", "blue", "green", "yellow", "white", "purple"][i % 6] if i < 6 else "test", tone=300 + i * 40, loud_at=3.0)
        clips.append({"id": f"k{i}", "file": f"k{i}.mp4", "status": "done", "start": i * 30.0, "end": i * 30.0 + 20,
                      "score": 60 + i * 3, "title": f"Clip {i} 🔥", "hook": f"HOOK {i}", "category": "clutch" if i % 2 else "fail",
                      "description": "what happens"})
    job = {"id": "j1", "user": UID, "creator": cid, "dir": str(d), "clips": clips, "kind": "video", "status": "done",
           "created": time.time(), "duration": 600, "title": "stream", "source": {}}
    jobs._jobs["j1"] = job
    jobs._by_user.setdefault(UID, {})["j1"] = job

    # ---------------------------------------------------------------- learning the page's style
    now = time.time()
    posting._posts[:] = []
    for i in range(12):
        posting._posts.append({"id": f"p{i}", "user": UID, "job": "j1", "clip": f"k{i}", "creator": cid, "account": "a1",
                               "account_name": "@gamextra00", "platform": "instagram", "status": "posted",
                               "posted_at": now - (3 + i) * 86400, "due_at": now - (3 + i) * 86400, "views": 1000 * (i + 1),
                               "title": f"Clip {i}", "score": 70, "remote_id": f"r{i}", "url": "", "tries": 0, "error": None, "created": now})
    seen = {}

    def fake_ask():
        seen["asked"] = True
        return "- Fail moments beat clutches here\n- Keep hooks under 5 words"
    notes = autopilot.learn_style(cid, ask=fake_ask)
    check("the style is learned from the page's own best and worst clips", seen.get("asked") and "Fail moments" in notes, notes)
    usage._where.creator = cid
    rules = brain._game_rules("")
    usage._where.creator = None
    check("...and every new title follows it", "What works on this page" in rules and "Keep hooks under 5 words" in rules)
    check("too few posts: nothing is learned", autopilot.learn_style("nobody", ask=fake_ask) == "")

    # ---------------------------------------------------------------- hook formats
    creators.update(cid, {"formats": True})
    usage._where.creator = cid
    check("hook formats are added when switched on", "Hook format" in brain._game_rules(""))
    usage._where.creator = None
    creators.update(cid, {"formats": False})

    # ---------------------------------------------------------------- hook test
    titles = autopilot.hook_variants(clips[0], 3, ask=lambda: ["POV: you're cooked 💀", "Clip 0 🔥", "Bhai ye kya tha?"])
    check("each page gets a different title, the clip's own first", titles == ["Clip 0 🔥", "POV: you're cooked 💀", "Bhai ye kya tha?"], titles)
    posting._posts[:] = []
    made = posting.enqueue(job, clips[11], ["a0", "a1", "a2"])
    autopilot.apply_hook_test(job, clips[11], made, ask=lambda: ["Title B", "Title C"])
    check("the posts carry the test titles", [p.get("title_override", "") for p in made] == ["", "Title B", "Title C"] and [p["variant"] for p in made] == [0, 1, 2])
    for p, v in zip(made, (900, 5000, 1000)):
        p.update(status="posted", posted_at=time.time() - 2 * 86400, views=v)
    growth._usual = lambda aid: 1000            # noqa: E731
    autopilot._hook_results()
    check("after a day the winning title is remembered", autopilot._state()["hook_wins"][cid] == ["Title B"])

    # ---------------------------------------------------------------- smart queue
    posting._posts[:] = []
    import datetime as dt
    from zoneinfo import ZoneInfo
    tomorrow = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date() + dt.timedelta(days=1)
    at = lambda h: dt.datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()  # noqa: E731
    low = posting.enqueue(job, clips[0], ["a1"], at=at(21))[0]          # weak clip got prime time
    high = posting.enqueue(job, clips[10], ["a1"], at=at(12))[0]        # strong clip got lunchtime
    low["due_at"], high["due_at"] = at(21), at(12)
    t_low, t_high = low["due_at"], high["due_at"]
    autopilot.smart_order(now=t_high - 3600)          # (both slots within the next day, whatever time it is now)
    check("the strongest clip moves to the prime-time slot", high["due_at"] == t_low and low["due_at"] == t_high, (low["due_at"], high["due_at"]))
    posting.reschedule(low["id"], t_low + 600)
    check("a post you moved yourself is left where you put it", low.get("pinned"))

    # ---------------------------------------------------------------- duplicate guard
    posting._posts[:] = []
    h1 = autopilot.phash(d / "clips" / "k0.mp4")
    check("a clip has a picture fingerprint", len(h1) == 3)
    h6 = autopilot.phash(d / "clips" / "k6.mp4")
    check("the same video matches itself", autopilot.same_video(h6, autopilot.phash(d / "clips" / "k6.mp4")))
    check("plain single-colour frames never count as the same video", not autopilot.same_video(h1, autopilot.phash(d / "clips" / "k1.mp4")))
    check("a different picture doesn't match", not autopilot.same_video(h6, h1))
    posting.enqueue(job, clips[2], ["a1"])
    dup = dict(clips[2], id="k2b", start=clips[2]["start"] + 3, end=clips[2]["end"] + 3)
    job["clips"].append(dup)
    check("an overlapping cut of the same moment isn't queued again", posting.enqueue(job, dup, ["a1"]) == [])
    check("...but can still go to another page", len(posting.enqueue(job, dup, ["a2"])) == 1)
    job["clips"].remove(dup)

    # ---------------------------------------------------------------- viral booster
    posting._posts[:] = []
    creators.update(cid, {"viral_boost": True})
    vp = posting.enqueue(job, clips[5], ["a1"])[0]
    vp.update(status="posted", posted_at=time.time() - 3600, views=9000, remote_id="ig1")
    growth._usual = lambda aid: 1000            # noqa: E731
    queued = []
    real_put = jobs._q.put
    jobs._q.put = lambda x: queued.append(x)
    autopilot._viral()
    others = [p for p in posting._mine() if p["clip"] == "k5" and p["account"] in ("a0", "a2")]
    check("a viral post goes to the creator's other pages at once", len(others) == 2 and all(p["due_at"] <= time.time() + 5 for p in others))
    ext = next((k for k in job["clips"] if k.get("extended_of") == "k5"), None)
    check("...and a longer cut of the moment is made", ext and ext["end"] - ext["start"] == 48 and queued and queued[0][2] == ext["id"], ext)
    autopilot._viral()
    check("a post is boosted only once", len([k for k in job["clips"] if k.get("extended_of") == "k5"]) == 1
          and len([p for p in posting._mine() if p["clip"] == "k5"]) == 3)
    jobs._q.put = real_put
    job["clips"].remove(ext)

    # ---------------------------------------------------------------- fast live, series
    c = creators.update(cid, {"fast_live": True, "series": True})
    check("fast live: a 90+ live clip posts now", autopilot.fast_live({"kind": "live"}, {"score": 93}, c))
    check("...not a normal video, not a weaker clip", not autopilot.fast_live({"kind": "video"}, {"score": 99}, c)
          and not autopilot.fast_live({"kind": "live"}, {"score": 80}, c))
    check("series titles number clips by where they are in the video", autopilot.series_title(job, clips[3], "Big clutch") == "Part 4 | Big clutch")

    # ---------------------------------------------------------------- reach-drop alarm
    posting._posts[:] = []
    for i in range(6):
        posting._posts.append({"id": f"n{i}", "user": UID, "job": "j1", "clip": f"k{i}", "creator": cid, "account": "a2", "platform": "facebook",
                               "status": "posted", "posted_at": time.time() - (2 + i) * 86400 / 1.5, "due_at": 0, "views": 100, "title": "t", "account_name": "FB"})
        posting._posts.append({"id": f"o{i}", "user": UID, "job": "j1", "clip": f"k{i + 6}", "creator": cid, "account": "a2", "platform": "facebook",
                               "status": "posted", "posted_at": time.time() - (9 + i) * 86400, "due_at": 0, "views": 1000, "title": "t", "account_name": "FB"})
    r = autopilot.reach_drop("a2")
    check("a page's reach drop is measured", r is not None and abs(r - 0.1) < 0.01, r)
    autopilot._reach()
    check("...and posting there is slowed", autopilot.slowed("a2") and not autopilot.slowed("a1"))
    for i in range(2):
        posting._posts.append({"id": f"t{i}", "user": UID, "job": "j1", "clip": "k0", "creator": cid, "account": "a2", "platform": "facebook",
                               "status": "posted", "posted_at": time.time() - 60, "due_at": 0, "views": 1, "title": "t", "account_name": "FB"})
    p3 = {"id": "x", "account": "a2", "due_at": time.time()}
    check("a slowed page posts at most 2 a day; the third waits for tomorrow", autopilot.hold_if_slowed(p3) and p3["due_at"] > time.time() + 80000)

    # ---------------------------------------------------------------- copyright guard
    posting._posts[:] = []
    yp = posting.enqueue(job, clips[7], ["a0"])[0]
    yp.update(status="posted", posted_at=time.time() - 3600, remote_id="vid1")
    accounts.youtube_status = lambda acc, ids: {"vid1": {"uploadStatus": "rejected", "rejectionReason": "copyright"}}
    creators.update(cid, {"autopost": True})
    autopilot._copyright()
    check("a clip YouTube blocks for copyright stops auto-posting for that creator", creators.get(cid)["autopost"] is False and yp["blocked"] == "copyright")
    creators.update(cid, {"autopost": True})

    # ---------------------------------------------------------------- slot filler
    posting._posts[:] = []
    nowt = time.time()
    lt = time.localtime(nowt + 3600)
    creators.update(cid, {"fill_slots": True, "post_times": f"{lt.tm_hour:02d}:{lt.tm_min:02d}", "post_min_score": 75,
                          "accounts": ["a1"], "daily_cap": 5})
    n = autopilot._fill_slots(now=nowt)
    got = [p for p in posting._mine() if p["account"] == "a1"]
    check("an empty planned slot gets the best clip not posted there yet", n == 1 and got and got[0]["clip"] == "k11", [p["clip"] for p in got])
    check("...and a filled slot is left alone", autopilot._fill_slots(now=nowt) == 0)

    # ---------------------------------------------------------------- streamer finder and competitors
    vids = [{"title": "insane clutch", "channel": "Mortal", "channel_url": "u1", "views": 900000},
            {"title": "bgmi 1v4", "channel": "Jonathan", "channel_url": "https://www.youtube.com/@Jonathan", "views": 500000},
            {"title": "funny", "channel": "Jonathan", "channel_url": "https://www.youtube.com/@Jonathan", "views": 100000},
            {"title": "new guy", "channel": "Snax", "channel_url": "", "views": 50000}]
    found = autopilot.find_streamers("BGMI", search=lambda g: vids)
    check("new streamers are found, your own creators left out", [r["name"] for r in found] == ["Jonathan", "Snax"] and found[0]["views"] == 600000)
    check("...each with a ready permission message", "Jonathan" in found[0]["message"])
    accounts.save_settings({"competitors": ["https://www.youtube.com/@clippage"]})
    comp = autopilot.competitors(list_feed=lambda url, n: [{"title": "Mortal 1v4 clutch", "views": 50000, "url": "x"},
                                                           {"title": "other", "views": 9000, "url": "y"}])
    check("competitor pages show their top Shorts, marking your creators' moments", comp[0]["videos"][0]["about_yours"] == ["mortal"])
    try:
        accounts.save_settings({"competitors": ["https://evil.example"]})
        check("only YouTube channel links are watched", False)
    except ValueError:
        check("only YouTube channel links are watched", True)

    # ---------------------------------------------------------------- English subtitles
    words = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.35} for i, w in enumerate("bhai kya shot maara yaar dekho".split())]
    en = autopilot.english_words(words, ask=lambda: ["bro what a shot", "look man"])
    check("Hinglish captions become English, in the same time span", " ".join(w["w"] for w in en) == "bro what a shot look man"
          and en[0]["s"] == 0 and en[-1]["e"] <= words[-1]["e"] + 0.01, en)
    try:
        autopilot.english_words(words, ask=lambda: ["only one"])
        check("a translation that loses lines is not used", False)
    except ValueError:
        check("a translation that loses lines is not used", True)
    creators.update(cid, {"en_subs": True, "accounts": ["a1"]})
    check("no English page: no English version", not autopilot.wants_english_version(creators.get(cid)))
    accounts.set_lang("a1", "english")
    check("an English page: an English version is made", autopilot.wants_english_version(creators.get(cid)))

    # ---------------------------------------------------------------- best cover
    cov = d / "clips" / "cover.mp4"
    make_video(cov, color="test", loud_at=5.0)
    ms = autopilot.best_cover_ms(cov)
    check("the cover is the clip's biggest moment", 4800 <= ms <= 6200, ms)

    # ---------------------------------------------------------------- Telegram channel
    try:
        accounts.connect_key("telegram", {"token": "bad", "chat": "@x"})
        check("a wrong bot token is refused", False)
    except ValueError:
        check("a wrong bot token is refused", True)
    import httpx

    class R:
        status_code = 200

        def json(self):
            return {"result": {"title": "GameXtra Clips"}}
    httpx.get = lambda *a, **k: R()
    t = accounts.connect_key("telegram", {"token": "123456789:" + "A" * 35, "chat": "@gamextraclips"})
    check("a Telegram channel connects", t["name"] == "GameXtra Clips" and t["platform"] == "telegram")

# ---------------------------------------------------------------- Facebook by token
with ctx.as_user(UID):
    class F:
        def __init__(self, d, code=200):
            self.d, self.status_code, self.text = d, code, str(d)

        def json(self):
            return self.d
    def fake_get(url, params=None, headers=None, **k):
        tok = (headers or {}).get("Authorization", "")
        if url.endswith("/me"):
            check("the token check never asks a person for Page-only fields", "category" not in (params or {}).get("fields", ""))
            return F({"id": "77", "name": "GameXtra Page", "metadata": {"type": "page"}} if "PAGE" in tok
                     else {"id": "1", "name": "Aditya", "metadata": {"type": "user"}})
        if url.endswith("/me/accounts"):
            return F({"data": [{"id": "55", "name": "GameXtra", "access_token": "pt", "instagram_business_account": {"id": "99", "username": "gamextra00"}}]})
        if url.endswith("/77"):
            return F({"id": "77", "name": "GameXtra Page"})
        return F({"error": {"message": "nope"}}, 400)
    httpx.get = fake_get
    try:
        accounts.facebook_by_token("not-a-token")
        check("a wrong Facebook token is refused", False)
    except ValueError:
        check("a wrong Facebook token is refused", True)
    r = accounts.facebook_by_token("EA" + "u" * 60)
    names = {a["id"]: a["name"] for a in accounts.list_accounts()}
    check("a user token adds the Pages and their Instagram", names.get("fb_55") == "GameXtra" and names.get("ig_99") == "@gamextra00", names)
    r = accounts.facebook_by_token("EAPAGE" + "p" * 60)
    check("a Page token adds that Page", accounts.get("fb_77")["page_id"] == "77" and r["name"] == "GameXtra Page")

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
