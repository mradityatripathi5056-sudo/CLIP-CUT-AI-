"""Comments on all recent videos of a connected page (your own uploads too), shown even while replies are off,
and replied to once replies are turned on."""
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-rep2-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="")
sys.path.insert(0, ".")
from studio import accounts, config, ctx, db, replies  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


now = time.time()
iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))


def fake_get(url, **kw):
    if url.endswith("/channels"):
        return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}
    if url.endswith("/playlistItems"):
        return {"items": [{"contentDetails": {"videoId": "vidA", "videoPublishedAt": iso}, "snippet": {"title": "My own Short"}},
                          {"contentDetails": {"videoId": "old", "videoPublishedAt": "2020-01-01T00:00:00Z"}, "snippet": {"title": "Old"}}]}
    if url.endswith("/commentThreads"):
        assert kw["params"]["videoId"] == "vidA"
        return {"items": [{"id": "c1", "snippet": {"topLevelComment": {"snippet": {"authorDisplayName": "Rahul", "textOriginal": "bhai kya clutch tha 🔥",
                                                                                     "authorChannelId": {"value": "someone"}}}}},
                          {"id": "c2", "snippet": {"topLevelComment": {"snippet": {"authorDisplayName": "Me", "textOriginal": "thanks all",
                                                                                     "authorChannelId": {"value": "CH1"}}}}}]}
    raise AssertionError(url)


replies._get = fake_get
accounts._yt_token = lambda acc: "tok"
with ctx.as_user("owner_rep"):
    accounts._put({"id": "yt_CH1", "platform": "youtube", "name": "GameXtra", "added": now, "token": "t"})
    config.ai_ready = lambda: False
    replies._check()
    L = replies.listing()
    items = L["items"]
    check("comments on your own uploads show up (not only the app's posts)", [i["text"] for i in items] == ["bhai kya clutch tha 🔥"], items)
    check("...as new, even while replies are off", items and items[0]["status"] == "new" and items[0]["post_title"] == "My own Short")
    check("your own comments are left out", all(i["author"] != "Me" for i in items))
    check("old videos are left out", all(i["post_title"] != "Old" for i in items))
    replies._check()
    check("a comment is shown once", len(replies.listing()["items"]) == 1)
    sent = []
    replies.send_reply = lambda acc, it: sent.append(it["reply"])
    replies.send(items[0]["id"], "Thanks bhai 🙌")
    check("you can answer a new comment by hand", sent == ["Thanks bhai 🙌"] and replies.listing()["items"][0]["status"] == "sent")

    # turned on later: a comment still waiting gets an AI reply
    d = replies._data()
    d["items"][0]["status"], d["items"][0]["reply"] = "new", ""
    replies._store(d)
    accounts.save_settings({"reply_mode": "approve"})
    config.ai_ready = lambda: True
    replies.write = lambda comments, title, tone: {c["cid"]: "Haan bhai, ekdum mast tha 🔥" for c in comments}
    replies._check()
    it = replies.listing()["items"][0]
    check("once replies are on, the waiting comment gets a reply to approve", it["status"] == "draft" and it["reply"].startswith("Haan bhai"))
    check("...without showing it twice", len(replies.listing()["items"]) == 1)
    accounts.save_settings({"reply_all": False})
    replies._get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not read the page"))
    replies._check()
    check("'only the app's posts' doesn't read the page", True)

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
