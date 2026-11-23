"""The Manager does what it's told: any creator setting (one creator or all), hashtags on every post, app settings,
daily limits, page language, editing a waiting post. Also: your own hashtags come first and Instagram gets at most
5 (Threads 1). Nothing outside this machine is contacted."""
import json
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-mgr2-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="")
sys.path.insert(0, ".")
from studio import accounts, brain, config, creators, ctx, db, manager, posting  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


config.ai_ready = lambda: True
plan = []


def fake_ai(prompt, schema=None, purpose=""):
    """Round 1: the planned actions; round 2: a short reply."""
    if "<tool_results>" in prompt:
        return {"reply": "Ho gaya bhai ✅", "actions": []}, "m", 0
    return {"reply": "", "actions": [{"tool": t, "args": json.dumps(a)} for t, a in plan]}, "m", 0


brain.ask_ai = fake_ai
UID = "owner_mgr2"
with ctx.as_user(UID):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "GameXtra", "added": time.time(), "token": "t"})
    accounts._put({"id": "ig_1", "platform": "instagram", "name": "@gamextra00", "added": time.time(), "token": "t", "user_id": "1"})
    a = creators.create({"name": "Techno Gamerz"})
    b = creators.create({"name": "Mortal"})

    plan[:] = [("set_hashtags", {"creator": "all", "tags": "#trending #viral #edit #game"})]
    r = manager.chat("Yaar main chahta hoon ab se trending viral edit game ye sab hashtags bhi use karo.")
    check("the Manager sets hashtags for every creator when none is named",
          creators.get(a["id"])["always_tags"] == creators.get(b["id"])["always_tags"] == "#trending #viral #edit #game", r)
    check("...and answers", r == "Ho gaya bhai ✅")

    plan[:] = [("set_hashtags", {"creator": "Mortal", "tags": "bgmi", "mode": "add"}), ("set_hashtags", {"creator": "Techno", "tags": "#edit", "mode": "remove"})]
    manager.chat("Mortal mein #bgmi bhi daalo aur Techno se edit hata do")
    check("hashtags can be added and removed per creator", creators.get(b["id"])["always_tags"].endswith("#bgmi")
          and "#edit" not in creators.get(a["id"])["always_tags"])

    plan[:] = [("update_creator", {"creator": "all", "settings": {"music_on": True, "post_mode": "instant", "yt_category": "20", "nonsense": 1}})]
    manager.chat("sab creators ke liye music on karo aur instant upload")
    check("ANY creator setting can be changed, for all creators", all(creators.get(x["id"])["music_on"] and creators.get(x["id"])["post_mode"] == "instant" for x in (a, b)))
    check("...unknown keys are ignored, not guessed", "nonsense" not in creators.get(a["id"]))
    plan[:] = [("update_creator", {"creator": "techno gamerz", "settings": {"id": "hack", "rotate_next": 5, "autopost": False}})]
    manager.chat("techno ka autopost band karo")
    check("the app's own bookkeeping can't be changed", creators.get(a["id"])["autopost"] is False and creators.get(a["id"])["id"] == a["id"])

    plan[:] = [("update_settings", {"settings": {"reply_mode": "auto", "reply_days": 7, "telegram_token": "x"}})]
    manager.chat("comments ka reply automatic kar do, 7 din tak")
    st = accounts.settings()
    check("app settings change from chat", st["reply_mode"] == "auto" and st["reply_days"] == 7)
    check("...but never keys or tokens", not st.get("telegram_token"))

    plan[:] = [("daily_limit", {"account": "GameXtra", "limit": 5}), ("page_language", {"account": "@gamextra00", "lang": "english"})]
    manager.chat("youtube pe 5 reels roz aur insta english mein")
    check("daily limit and page language change from chat", accounts.get("yt_1")["daily_limit"] == 5 and accounts.get("ig_1")["lang"] == "english")

    posting._posts.append({"id": "p1", "user": UID, "status": "scheduled", "title": "old", "account": "yt_1", "account_name": "GameXtra",
                           "due_at": time.time() + 3600, "job": "j", "clip": "k", "creator": b["id"], "platform": "youtube"})
    plan[:] = [("edit_post", {"post": "p1", "title": "Mortal ka 1v4 🔥"})]
    manager.chat("next post ka title badlo")
    check("a waiting post's title can be changed", posting._posts[-1]["title_override"] == "Mortal ka 1v4 🔥")

    log = manager.state()["log"] if "log" in manager.state() else manager._data().get("log", [])
    check("what it did is written down", any("set_hashtags" in (x.get("text") if isinstance(x, dict) else str(x)) for x in log))

    # "make and post 2 clips from Total Gaming's channel": a channel link becomes its newest video, once
    import studio.autofetch as af  # noqa: E402
    from studio import jobs  # noqa: E402
    af.list_feed = lambda url, n=10: [{"id": "live1", "url": "https://www.youtube.com/watch?v=live1", "title": "LIVE", "live": True, "duration": 0},
                                      {"id": "v9", "url": "https://www.youtube.com/watch?v=v9", "title": "BGMI rush", "live": False, "duration": 900}]
    made_jobs = []
    jobs.create = lambda src, opts, creator=None, **k: made_jobs.append((src, creator)) or {"id": f"j{len(made_jobs)}", "clips": []}
    jobs.save = lambda j: None
    plan[:] = [("clip_video", {"url": "https://www.youtube.com/@totalgaming093/videos?view=0", "creator": "Mortal", "post": 2}),
               ("clip_video", {"url": "https://www.youtube.com/@totalgaming093/videos?view=0", "creator": "Mortal", "post": 2})]
    manager.chat("bna ke post kar do 2 clips turant Total gaming ke channel se")
    check("a channel link is turned into its newest finished video", made_jobs and made_jobs[0][0]["url"] == "https://www.youtube.com/watch?v=v9")
    check("...and the same action isn't run twice in one answer", len(made_jobs) == 1, made_jobs)
    check("channel, tab and playlist links are spotted", af.is_list_link("https://www.youtube.com/@totalgaming093/videos?view=0")
          and af.is_list_link("https://www.twitch.tv/mortal") and not af.is_list_link("https://www.youtube.com/watch?v=abc"))

    # the best 2 clips go out as soon as they're ready, whatever the creator's plan
    creators.update(b["id"], {"accounts": ["yt_1"], "autopost": False})
    posting._posts[:] = []
    job = {"id": "jt", "creator": b["id"], "post_top": 2, "clips": [
        {"id": "c1", "score": 60, "status": "done"}, {"id": "c2", "score": 95, "status": "queued"}, {"id": "c3", "score": 90, "status": "done"}]}
    got = []
    real_enqueue = posting.enqueue
    posting.enqueue = lambda j, k, accs, now=False, **kw: got.append((k["id"], now)) or [1]
    posting.on_clip_ready(job, job["clips"][0])
    posting.on_clip_ready(job, job["clips"][2])
    job["clips"][1]["status"] = "done"
    posting.on_clip_ready(job, job["clips"][1])
    posting.on_clip_ready(job, job["clips"][1])
    check("only the 2 best clips are posted, right away, once each", got == [("c3", True), ("c2", True)], got)
    posting.enqueue = real_enqueue

# ---------------------------------------------------------------- hashtags in posts
cap = posting._caption({"description": "clutch", "hashtags": ["bgmi", "mortal", "clutch", "1v4"]},
                       {"always_tags": "#trending #viral #edit #game", "cta_text": "", "post_footer": ""}, "", ["esports"])
check("your own hashtags come first", cap.split("\n\n")[-1].startswith("#trending #viral #edit #game #bgmi"))
check("Instagram gets at most 5 hashtags", posting.cap_hashtags(cap, 5).count("#") == 5)
check("Threads gets 1", posting.cap_hashtags(cap, 1).count("#") == 1)
check("other platforms keep them all", posting.cap_hashtags(cap, None).count("#") == 9)
check("text like 'C#' or '&#39' isn't cut", posting.cap_hashtags("I code C# &#39; #a #b", 1) == "I code C# &#39; #a")

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
