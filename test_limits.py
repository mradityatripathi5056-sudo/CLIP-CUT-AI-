"""Daily limit per page: counts the app's posts and posts made by hand on the page itself (India date), checks the
page first when the app opens again, then every 2 hours, and moves a post that would go over to the next day."""
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-lim-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="")
sys.path.insert(0, ".")
from studio import accounts, creators, ctx, db, limits, posting  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


UID = "owner_lim"
now = time.time()
today = limits.day(now)
reads = []
page = {"ids": [("hand1", today)]}          # one Short posted by hand today


def fake_yt(acc, days):
    reads.append(time.time())
    return [x for x in page["ids"] if x[1] in days]


limits.READERS["youtube"] = fake_yt
with ctx.as_user(UID):
    accounts._put({"id": "yt1", "platform": "youtube", "name": "GameXtra", "added": now, "token": "t"})
    accounts._put({"id": "fb1", "platform": "facebook", "name": "GameXtra FB", "added": now, "token": "t", "page_id": "1"})
    check("a YouTube channel starts at 3 a day, other pages with no limit",
          limits.limit_of(accounts.get("yt1")) == 3 and limits.limit_of(accounts.get("fb1")) == 0)
    c = creators.create({"name": "Mortal", "accounts": ["yt1"]})
    job = {"id": "j1", "creator": c["id"], "clips": []}
    clip = {"id": "k1"}

    def post(i, status="posted", ago=600, rid=None):
        p = {"id": f"p{i}", "user": UID, "job": "j1", "clip": f"k{i}", "creator": c["id"], "account": "yt1", "platform": "youtube",
             "account_name": "GameXtra", "status": status, "due_at": now - ago, "posted_at": now - ago if status == "posted" else None,
             "remote_id": rid or f"v{i}", "title": "t", "tries": 0, "error": None, "created": now}
        posting._posts.append(p)
        return p
    post(1)
    limits.check("yt1")
    check("today's count = the app's posts + the ones posted by hand", limits.used("yt1", today) == 2)
    page["ids"].append(("v1", today))                       # the app's own post is also on the page: counted once
    limits.check("yt1")
    check("a post isn't counted twice when it's both the app's and on the page", limits.used("yt1", today) == 2)

    waiting = post(9, status="scheduled", ago=5)
    limits._checked_now.clear()                            # as if the app was just opened again
    reads.clear()
    check("with 2 of 3 used, the next post goes out", limits.hold(waiting) is False)
    check("...after the page was checked first (app just opened)", len(reads) == 1)
    post(2)
    reads.clear()
    held = limits.hold(waiting)
    check("with 3 of 3 used, the post waits for the next day", held and waiting["due_at"] > now + 80000 and "limit 3" in waiting["note"])
    check("...without reading the page again within 2 hours", reads == [])
    accounts.set_limit("yt1", 5)
    waiting["due_at"] = now - 5
    check("raise the limit to 5 and it goes out today", limits.hold(waiting) is False)
    accounts.set_limit("yt1", 0)
    check("0 means no limit", limits.hold(waiting) is False)
    try:
        accounts.set_limit("yt1", 99)
        check("limits above 50 are refused", False)
    except ValueError:
        check("limits above 50 are refused", True)
    accounts.set_limit("yt1", 3)

    def broken(acc, days):
        raise RuntimeError("quota")
    limits.READERS["youtube"] = broken
    row = limits.check("yt1")
    check("if YouTube can't be read, the last reading is kept and the app's posts still count", row["error"] and limits.used("yt1", today) == 3)
    limits._save({})

    # scheduling also respects the page's limit
    posting._posts[:] = []
    for i in range(3):
        post(i + 20, ago=60 * (i + 1))
    t = posting._next_slot("yt1", 30, 10)
    check("new posts are planned for a day that still has room", limits.day(t) != today, limits.day(t))
    st = {a["id"]: a for a in limits.status()}
    check("the dashboard shows today's count and the limit", st["yt1"]["today"] == 3 and st["yt1"]["limit"] == 3 and st["fb1"]["limit"] == 0)

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
