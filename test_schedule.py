"""Scheduling posts: a picked date and time, a creator's fixed posting times, moving a post, the calendar, and the
caption style. Runs against the code directly with its own empty data folder; nothing is posted anywhere."""
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-schedule-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="0", CLIPCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import accounts, auth, creators, ctx, db, jobs, posting, server  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


# ---- typing posting times
check("times are tidied and sorted", creators.clean_times("7pm, 10:00 ,14.30;9am") == "09:00, 10:00, 14:30, 19:00")
check("'7 pm' with a space is one time", creators.clean_times("7 pm, 10") == "10:00, 19:00")
check("nothing typed is no fixed times", creators.clean_times("") == "")
for bad in ("25:00", "10:75", "lunch", "13pm"):
    try:
        creators.clean_times(bad)
        check(f"'{bad}' is refused", False)
    except ValueError:
        check(f"'{bad}' is refused", True)


def new_clip(job, n, desc="Wait for it 😂🔥 Would you survive this? 👇"):
    c = {"id": f"c{n}", "status": "done", "file": f"c{n}.mp4", "title": f"Clip {n} 🔥", "hook": "WOW",
         "description": desc, "hashtags": ["gaming", "viral"], "score": 90}
    job["clips"].append(c)
    jobs.save(job)
    return c


me = auth.local_user()
with ctx.as_user(me.id):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "My Channel", "added": time.time()})
    accounts._put({"id": "fb_1", "platform": "facebook", "name": "My Page", "added": time.time(), "page_id": "1", "token": "t"})
    plain = creators.create({"name": "Plain"})
    fixed = creators.create({"name": "Fixed", "post_times": "10:00, 19:00", "daily_cap": 6})
    capped = creators.create({"name": "Capped", "post_times": "10:00, 19:00", "daily_cap": 1})
    try:
        creators.update(plain["id"], {"post_times": "noon-ish"})
        check("a creator cannot save a time that is not one", False)
    except ValueError:
        check("a creator cannot save a time that is not one", True)

    job = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=plain["id"])
    c1 = new_clip(job, 1)

    # ---- a picked date and time
    at = time.time() + 3 * 3600
    made = posting.enqueue(job, c1, ["yt_1", "fb_1"], at=at)
    check("a picked time is used for every account", [round(p["due_at"]) for p in made] == [round(at)] * 2)
    try:
        posting.enqueue(job, new_clip(job, 2), ["yt_1"], at=time.time() - 3600)
        check("a time that has passed is refused", False)
    except ValueError:
        check("a time that has passed is refused", True)

    # ---- moving a post
    later = time.time() + 26 * 3600
    posting.reschedule(made[0]["id"], later)
    check("a waiting post can be moved", round(posting._mine()[0]["due_at"]) == round(later))
    posting.cancel(made[1]["id"])
    posting.reschedule(made[1]["id"], later)
    check("a cancelled post can be put back at a new time", next(p for p in posting._mine() if p["id"] == made[1]["id"])["status"] == "scheduled")
    try:
        posting.reschedule("nope", later)
        check("an unknown post cannot be moved", False)
    except ValueError:
        check("an unknown post cannot be moved", True)

    # ---- fixed posting times
    fjob = jobs.create({"type": "file", "path": "", "name": "f.mp4"}, {}, enqueue=False, creator=fixed["id"])
    dues = [posting.enqueue(fjob, new_clip(fjob, 10 + i), ["yt_1"])[0]["due_at"] for i in range(3)]
    hm = [time.strftime("%H:%M", time.localtime(t)) for t in dues]
    check("queued clips go out at the creator's times", set(hm) <= {"10:00", "19:00"}, str(hm))
    check("...each at its own time, in order", len(set(dues)) == 3 and dues == sorted(dues), str(hm))
    check("...and never in the past", min(dues) > time.time())

    cjob = jobs.create({"type": "file", "path": "", "name": "c.mp4"}, {}, enqueue=False, creator=capped["id"])
    d1 = posting.enqueue(cjob, new_clip(cjob, 20), ["fb_1"])[0]["due_at"]
    d2 = posting.enqueue(cjob, new_clip(cjob, 21), ["fb_1"])[0]["due_at"]
    check("one post a day: the next clip waits for the next day",
          time.strftime("%Y-%m-%d", time.localtime(d1)) != time.strftime("%Y-%m-%d", time.localtime(d2)))

    # ---- the calendar
    cal = posting.calendar(time.time() - 86400, time.time() + 40 * 86400)
    check("the calendar lists every planned post", len(cal) == 7, str(len(cal)))
    check("...in time order, with the creator's name", [p["at"] for p in cal] == sorted(p["at"] for p in cal) and cal[0]["creator_name"])
    check("...and only for the asked days", posting.calendar(time.time() + 300 * 86400, time.time() + 301 * 86400) == [])

    # ---- caption style
    hype = posting._caption(c1, dict(creators.DEFAULTS, caption_style="hype", cta_text="Follow for daily clips 🔥"))
    check("hype captions keep their emojis and add the call to action", "😂" in hype and "Follow for daily clips" in hype and "#gaming" in hype)
    clean = posting._caption(c1, dict(creators.DEFAULTS, caption_style="clean"))
    check("clean captions drop the emojis, keep the words", "😂" not in clean and "👇" not in clean and "Would you survive this?" in clean)
    check("clean titles drop them too", posting._title(c1, {"caption_style": "clean"}) == "Clip 1")
    own = dict(c1, fixed_description=True, description="Campaign text 🎯")
    check("a description typed by the person is never changed", "🎯" in posting._caption(own, dict(creators.DEFAULTS, caption_style="clean")))

# ---- the same through the web: schedule, move, calendar
cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
H = {"Origin": "http://127.0.0.1:8765"}
with ctx.as_user(me.id):
    c9 = new_clip(job, 9)
at = time.time() + 5 * 3600
r = cl.post("/api/posts", json={"job": job["id"], "clip": c9["id"], "accounts": ["yt_1"], "at": at}, headers=H)
check("a clip can be scheduled from the page", r.status_code == 200 and r.json()["queued"] == 1, r.text)
r = cl.post("/api/posts", json={"job": job["id"], "clip": c9["id"], "accounts": ["fb_1"], "at": "soon"}, headers=H)
check("a time that is not a time is refused plainly", r.status_code == 400, r.text)
r = cl.post("/api/posts", json={"job": job["id"], "clip": c9["id"], "accounts": ["fb_1"], "at": time.time() - 999}, headers=H)
check("...and so is one in the past", r.status_code == 400 and "passed" in r.text, r.text)
start = time.time() - 86400
r = cl.get("/api/calendar", params={"start": start, "end": start + 42 * 86400})
pid = next(p["id"] for p in r.json()["posts"] if p["clip"] == c9["id"])
check("the calendar answers for six weeks", r.status_code == 200 and len(r.json()["posts"]) == 8, r.text[:200])
check("...but not for a whole year at once", cl.get("/api/calendar", params={"start": start, "end": start + 365 * 86400}).status_code == 400)
r = cl.post(f"/api/posts/{pid}/reschedule", json={"at": at + 3600}, headers=H)
check("a post can be moved from the page", r.status_code == 200, r.text)
check("a move from another website is refused",
      cl.post(f"/api/posts/{pid}/reschedule", json={"at": at}, headers={"Origin": "https://evil.example"}).status_code == 403)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402
db.engine.dispose()
shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
