"""Autopilot: the app looks after the pages by itself and gets better from its own numbers.

- Learns the page's style: every Monday the AI compares the best and the weakest clips of a creator and writes
  short notes ("what works here"), which every new title, hook and caption then follows.
- Hook test: one clip goes out with a different title on each page; after a day the winning style is kept.
- Smart queue: the strongest clip waiting gets the prime-time slot, weaker ones the quieter slots.
- Viral booster: a post doing 3x the page's usual in its first hours goes to the creator's other pages at once,
  gets a "full moment" longer cut, and a first comment asking people to follow.
- Fast live mode, series titles (Part 1, 2, 3), a reach-drop alarm that slows posting, a copyright guard that
  stops a creator when YouTube blocks a video, a duplicate guard, a slot filler so no planned slot stays empty,
  English-subtitle versions for English pages, the best cover frame, varied hook formats, a streamer finder and
  a competitor tracker.

Everything here is a choice per creator (Setup, Autopilot); it never posts a creator's clips anywhere the creator
isn't set to post."""
import random
import re
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import accounts, alerts, auth, config, creators, ctx, jobs, posting

EVERY = 15 * 60
SWITCHES = ("style_learn", "hook_test", "smart_queue", "viral_boost", "fast_live", "series", "reach_guard",
            "copyright_guard", "no_duplicates", "fill_slots", "en_subs", "best_cover", "formats")
FORMATS = ["POV: <the situation>", "Wait for it 💀", "<Streamer> did WHAT? 😱", "Rate this play 1-10 👇",
           "Nobody expected this...", "The cleanest <thing> you'll see today", "Last second <thing> 🔥",
           "Is this the best <thing> ever?"]
PRIME = {"india": [21, 20, 22, 19, 18, 13], "global": [6, 7, 20, 23, 8]}   # India-time hours with the most viewers


def _state() -> dict:
    return accounts._read("autopilot.json", {})


def _save_state(d):
    accounts._write("autopilot.json", d)


def _clip_of(p):
    job = jobs.get(p["job"])
    clip = next((k for k in job["clips"] if k["id"] == p["clip"]), None) if job else None
    return job, clip


# ------------------------------------------------------------------ 1. learning the page's style
def style_notes(cid) -> str:
    return (_state().get("style", {}).get(cid) or {}).get("notes", "")


def learn_style(cid, ask=None) -> str:
    """Notes from the creator's best and weakest posts (and the hook test winners). Needs 10 posts with views."""
    from . import brain, growth
    rows = {}
    for p in growth._posted(None, 60):
        if p.get("creator") != cid:
            continue
        job, clip = _clip_of(p)
        if not clip:
            continue
        r = rows.setdefault(p["clip"], {"title": clip.get("title") or "", "hook": clip.get("hook") or "",
                                        "category": clip.get("category") or "", "views": 0, "len": clip["end"] - clip["start"]})
        usual = growth._usual(p["account"]) or 1
        r["views"] = max(r["views"], (p["views"] or 0) / usual)       # views against the page's usual
    if len(rows) < 10:
        return ""
    ranked = sorted(rows.values(), key=lambda r: -r["views"])
    k = max(3, len(ranked) // 10)
    top, low = ranked[:k], ranked[-k:]
    wins = _state().get("hook_wins", {}).get(cid, [])[-10:]
    line = lambda r: f"- [{r['category']}, {int(r['len'])}s, {r['views']:.1f}x usual] hook: {brain._safe(r['hook'], 80)} | title: {brain._safe(r['title'], 100)}"  # noqa: E731
    prompt = ("You coach a gaming clips page. Compare the clips that did best with those that did worst, and write "
              "at most 6 short, concrete rules for future hooks, titles and moment choice (what to do more, what to "
              "avoid). Plain text, one rule per line, no intro.\n\nBEST:\n" + "\n".join(map(line, top)) +
              "\n\nWORST:\n" + "\n".join(map(line, low)) +
              ("\n\nTITLES THAT WON A/B TESTS:\n" + "\n".join("- " + brain._safe(w, 100) for w in wins) if wins else ""))
    if ask is None:
        ask = lambda: brain.ask_ai(prompt, schema={"type": "OBJECT", "properties": {"rules": {"type": "STRING"}},  # noqa: E731
                                                   "required": ["rules"]}, purpose="learn style")[0]["rules"]
    try:
        notes = "\n".join(brain._text(x, 160) for x in str(ask()).splitlines() if x.strip())[:900]
    except Exception:  # noqa: BLE001
        cats = statistics.multimode([r["category"] for r in top]) if top else []
        notes = f"- Clips about {', '.join(cats)} do best on this page." if cats else ""
    if notes:
        d = _state()
        d.setdefault("style", {})[cid] = {"notes": notes, "at": time.time()}
        _save_state(d)
        creators.log(cid, "Autopilot learned what works on this page:\n" + notes)
    return notes


def _weekly_learning():
    d = _state()
    week = time.strftime("%Y-%W")
    for c in creators.all_creators():
        if c.get("style_learn", True) and (d.get("style", {}).get(c["id"]) or {}).get("week") != week:
            try:
                learn_style(c["id"])
            except Exception:  # noqa: BLE001
                pass
            d = _state()
            d.setdefault("style", {}).setdefault(c["id"], {})["week"] = week
            _save_state(d)


# ------------------------------------------------------------------ 2. hook test
def hook_variants(clip, n: int, ask=None) -> list:
    """n different titles for the same clip (the first is the clip's own)."""
    from . import brain
    own = clip.get("title") or clip.get("hook") or "Clip"
    if n < 2:
        return [own]
    if ask is None:
        def ask():
            out, _, _ = brain.ask_ai(
                f"Write {n - 1} different titles for this gaming clip, each in a clearly different style (question, "
                "shock, POV, numbers). Same language and emoji use as the original. No links or @ names.\n"
                f"ORIGINAL: {brain._safe(own, 120)}\nWHAT HAPPENS: {brain._safe(clip.get('description', ''), 300)}",
                schema={"type": "OBJECT", "properties": {"titles": {"type": "ARRAY", "items": {"type": "STRING"}}},
                        "required": ["titles"]}, purpose="hook test")
            return out["titles"]
    try:
        alts = [brain._text(t, 100) for t in ask() if str(t).strip()]
    except Exception:  # noqa: BLE001
        alts = []
    seen, out = set(), []
    for t in [own] + alts:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:n]


def apply_hook_test(job, clip, made: list, ask=None):
    """Each new post of this clip gets its own title."""
    if len(made) < 2:
        return
    titles = hook_variants(clip, len(made), ask)
    if len(titles) < 2:
        return
    with posting._lock:
        for i, p in enumerate(made):
            t = titles[i % len(titles)]
            if i:
                p.update(title=t, title_override=t)
            p["variant"] = i
        posting._save()


def _hook_results():
    """After a day: the title whose views (against its page's usual) were best is remembered as a winner."""
    from . import growth
    d = _state()
    done = set(d.get("hook_done", []))
    by = {}
    for p in posting._mine():
        if "variant" in p and p["status"] == "posted" and p.get("views") is not None:
            by.setdefault((p["job"], p["clip"]), []).append(p)
    for key, ps in by.items():
        k = "|".join(key)
        if k in done or len(ps) < 2 or any(time.time() - (p.get("posted_at") or 0) < 86400 for p in ps):
            continue
        best = max(ps, key=lambda p: (p["views"] or 0) / (growth._usual(p["account"]) or 1))
        d.setdefault("hook_wins", {}).setdefault(best["creator"], []).append(best["title"])
        d["hook_wins"][best["creator"]] = d["hook_wins"][best["creator"]][-30:]
        done.add(k)
    d["hook_done"] = sorted(done)[-500:]
    _save_state(d)


# ------------------------------------------------------------------ 3. smart queue
def _prime_rank(ts: float, audience: str) -> int:
    from zoneinfo import ZoneInfo
    import datetime as dt
    h = dt.datetime.fromtimestamp(ts, ZoneInfo("Asia/Kolkata")).hour
    order = PRIME.get(audience, PRIME["india"])
    return order.index(h) if h in order else len(order) + 1


def smart_order(now=None):
    """Within the next day, on each page, the best clip waiting takes the best slot (slots themselves don't move)."""
    now = now or time.time()
    groups = {}
    for p in posting._mine():
        if p["status"] == "scheduled" and now + 600 < p["due_at"] < now + 86400 and not p.get("pinned") and not p.get("recycle_of"):
            c = creators.get(p.get("creator"))
            if c and c.get("smart_queue", True):
                groups.setdefault(p["account"], []).append(p)
    moved = 0
    with posting._lock:
        for ps in groups.values():
            if len(ps) < 2:
                continue
            aud = (creators.get(ps[0]["creator"]) or {}).get("audience", "india")
            slots = sorted((p["due_at"] for p in ps), key=lambda t: (_prime_rank(t, aud), t))
            for p, t in zip(sorted(ps, key=lambda p: -(p.get("score") or 0)), slots):
                if p["due_at"] != t:
                    p["due_at"], moved = t, moved + 1
        if moved:
            posting._save()
    return moved


# ------------------------------------------------------------------ 4. viral booster
def _viral():
    from . import growth
    d = _state()
    boosted = set(d.get("boosted", []))
    for p in posting._mine():
        if (p["status"] != "posted" or p["id"] in boosted or p.get("views") is None
                or not (0 < time.time() - (p.get("posted_at") or 0) < 6 * 3600)):
            continue
        c = creators.get(p.get("creator"))
        if not c or not c.get("viral_boost"):
            continue
        usual = growth._usual(p["account"])
        if not usual or (p["views"] or 0) < max(500, usual * 3):
            continue
        boosted.add(p["id"])
        job, clip = _clip_of(p)
        if not clip:
            continue
        others = [a for a in c["accounts"] if a != p["account"]]
        made = posting.enqueue(job, clip, others, now=True) if others else []
        extra = extend_clip(job, clip)
        if p["platform"] == "youtube":
            try:
                accounts.youtube_comment(accounts.get(p["account"]), p["remote_id"],
                                         "Full moment aa raha hai 👀 Follow karo taaki miss na ho! 🔥" if c.get("audience", "india") == "india"
                                         else "The full moment is coming 👀 Follow so you don't miss it! 🔥")
            except Exception:  # noqa: BLE001
                pass
        creators.log(c["id"], f"Going viral ({p['views']:,} views, {p['views'] / usual:.0f}x usual): sent to "
                              f"{len(made)} more page(s){', and a longer cut is being made' if extra else ''}.")
        alerts.notify(f"🔥 {p['title']} is going viral on {p['account_name']} ({p['views']:,} views). Boosted.", kind="post")
    d["boosted"] = sorted(boosted)[-500:]
    _save_state(d)


def extend_clip(job, clip):
    """A longer cut of the same moment (8 s before, 20 s after), posted like a new clip."""
    if any(k.get("extended_of") == clip["id"] for k in job["clips"]):
        return None
    start, end = max(0.0, clip["start"] - 8), clip["end"] + 20
    if "src_offset" in clip:
        start, end = max(start, clip["src_offset"]), min(end, clip.get("src_end", end))
    elif job.get("duration"):
        end = min(end, job["duration"])
    if end - start < clip["end"] - clip["start"] + 5:
        return None
    import secrets
    new = {k: v for k, v in clip.items() if k not in ("file", "cover", "version", "made_at", "phash", "english", "file_en", "music_song")}
    title = clip.get("title") or clip.get("hook") or "Clip"
    new.update(id="x" + secrets.token_hex(4), start=round(start, 2), end=round(end, 2), status="queued", extended_of=clip["id"],
               title=("Full moment: " + title)[:100])
    job["clips"].append(new)
    jobs.save(job)
    jobs._q.put(("clip", job["id"], new["id"]))
    return new


# ------------------------------------------------------------------ 5. fast live, 6. series
def fast_live(job, clip, c) -> bool:
    return bool(c.get("fast_live") and job.get("kind") == "live" and clip.get("score", 0) >= 90)


def series_title(job, clip, title: str) -> str:
    """'Part 2 | title' when several clips of one video go out."""
    done = [k for k in job.get("clips", []) if k.get("status") == "done" and not k.get("extended_of")]
    if len(done) < 2:
        return title
    order = sorted(done, key=lambda k: k["start"])
    n = next((i + 1 for i, k in enumerate(order) if k["id"] == clip["id"]), 0)
    return f"Part {n} | {title}"[:100] if n else title


# ------------------------------------------------------------------ 7. reach-drop alarm
def reach_drop(account_id) -> float | None:
    """The last 7 days' median views as a share of the 21 days before; None when there's too little to say."""
    from . import growth
    now = time.time()
    rows = [p for p in growth._posted([account_id], 30)]
    new = [p["views"] or 0 for p in rows if now - p["posted_at"] < 7 * 86400 and now - p["posted_at"] > 86400]
    old = [p["views"] or 0 for p in rows if now - p["posted_at"] >= 7 * 86400]
    if len(new) < 5 or len(old) < 5 or not statistics.median(old):
        return None
    return statistics.median(new) / statistics.median(old)


def slowed(account_id) -> bool:
    return _state().get("slow", {}).get(account_id, 0) > time.time()


def _reach():
    d = _state()
    for a in accounts.list_accounts():
        guarded = [c for c in creators.all_creators() if a["id"] in c["accounts"] and c.get("reach_guard", True)]
        if not guarded or slowed(a["id"]):
            continue
        r = reach_drop(a["id"])
        if r is not None and r < 0.4:
            d.setdefault("slow", {})[a["id"]] = time.time() + 3 * 86400
            for c in guarded:
                creators.log(c["id"], f"Reach on {a['name']} dropped to {r:.0%} of normal. Posting there is slowed "
                                      "to 2 a day for 3 days and trending hashtags are left out.")
            alerts.notify(f"⚠️ reach on {a['name']} fell to {r:.0%} of normal this week. Autopilot slowed posting there "
                          "for 3 days. Check the page for warnings.", kind="post")
    _save_state(d)


def hold_if_slowed(p) -> bool:
    """Called before a post goes out: a slowed page posts at most 2 a day; the rest moves to tomorrow."""
    if not slowed(p["account"]):
        return False
    today = time.strftime("%Y-%m-%d")
    n = sum(1 for x in posting._mine() if x["account"] == p["account"] and x["status"] == "posted"
            and time.strftime("%Y-%m-%d", time.localtime(x.get("posted_at") or 0)) == today)
    if n < 2:
        return False
    p["due_at"] = p["due_at"] + 86400
    return True


# ------------------------------------------------------------------ 8. copyright guard
def _copyright():
    by_acc = {}
    for p in posting._mine():
        if p["platform"] == "youtube" and p["status"] == "posted" and p.get("remote_id") and time.time() - (p.get("posted_at") or 0) < 14 * 86400:
            by_acc.setdefault(p["account"], []).append(p)
    for aid, ps in by_acc.items():
        acc = accounts.get(aid)
        if not acc:
            continue
        try:
            st = accounts.youtube_status(acc, [p["remote_id"] for p in ps])
        except Exception:  # noqa: BLE001
            continue
        for p in ps:
            s = st.get(p["remote_id"])
            if s is None or p.get("blocked"):
                continue
            if s.get("uploadStatus") == "rejected" or s.get("rejectionReason"):
                p["blocked"] = s.get("rejectionReason") or s.get("uploadStatus")
                c = creators.get(p["creator"])
                if c and c.get("copyright_guard", True) and p["blocked"] in ("copyright", "claim", "rejected", "duplicate", "trademark"):
                    creators.update(c["id"], {"autopost": False})
                    creators.log(c["id"], f"YouTube blocked \"{p['title']}\" ({p['blocked']}). Auto-posting for "
                                          f"{c['name']} is stopped so the channel doesn't get a strike. Check it, then turn it back on.")
                    alerts.notify(f"🛑 YouTube blocked a clip of {c['name']} ({p['blocked']}). Auto-posting for them is off.", kind="post")
        posting._save()


# ------------------------------------------------------------------ 9. duplicate guard
def phash(path: Path) -> list:
    """Three 64-bit difference hashes (at 25%, 50% and 75% of the clip)."""
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                   capture_output=True, text=True, timeout=30).stdout or 0)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in (0.25, 0.5, 0.75):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * f:.2f}", "-i", str(path), "-frames:v", "1", "-vf",
                              "scale=9:8,format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=30).stdout
        if len(raw) < 72:
            continue
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | (raw[y * 9 + x] > raw[y * 9 + x + 1])
        out.append(bits)
    return out


def _hash_of(job, clip):
    if not clip.get("phash") and clip.get("file"):
        p = Path(job["dir"]) / "clips" / clip["file"]
        if p.is_file():
            clip["phash"] = phash(p)
    return clip.get("phash") or []


def same_video(a: list, b: list) -> bool:
    if not a or not b:
        return False
    flat = lambda h: not 4 <= bin(h).count("1") <= 60       # a plain or black frame says nothing  # noqa: E731
    close = sum(1 for x, y in zip(a, b) if not flat(x) and not flat(y) and bin(x ^ y).count("1") <= 10)
    return close >= 2


def is_duplicate(job, clip, account_id) -> bool:
    """The same moment (overlapping time in the same video, or a near-identical picture) already went, or is going,
    to this page."""
    mine = [p for p in posting._mine() if p["account"] == account_id and p["status"] in ("posted", "scheduled", "posting")
            and not (p["job"] == job["id"] and p["clip"] == clip["id"])]
    for p in mine:
        if p["job"] == job["id"]:
            k = next((x for x in job["clips"] if x["id"] == p["clip"]), None)
            if k and not clip.get("extended_of") and k["id"] != clip.get("extended_of") and \
                    min(k["end"], clip["end"]) - max(k["start"], clip["start"]) > 0.5 * (clip["end"] - clip["start"]):
                return True
    h = _hash_of(job, clip)
    if not h:
        return False
    for p in mine[-60:]:
        j2, k2 = _clip_of(p)
        if k2 and j2 and k2.get("phash") and same_video(h, k2["phash"]):
            return True
    return False


# ------------------------------------------------------------------ 10. slot filler
def _fill_slots(now=None):
    """A planned time in the next 2 hours with nothing on a page: fill it with the best clip not posted there yet,
    or else an old hit with new text."""
    from . import growth
    now = now or time.time()
    filled = 0
    for c in creators.all_creators():
        if not (c.get("fill_slots") and c.get("autopost") and c["accounts"] and creators.times_of(c)):
            continue
        for aid in c["accounts"]:
            nxt = posting._next_slot(aid, c["post_gap_min"], c["daily_cap"], creators.times_of(c))
            if not nxt or nxt - now > 2 * 3600:
                continue                      # the next free planned time is far off (or today's are all taken)
            posted = {(p["job"], p["clip"]) for p in posting._mine() if p["account"] == aid and p["status"] in ("posted", "scheduled", "posting")}
            pick = None
            for j in jobs.list_jobs():
                if j.get("creator") != c["id"]:
                    continue
                job = jobs.get(j["id"])
                for k in (job or {}).get("clips", []):
                    if (k.get("status") == "done" and (job["id"], k["id"]) not in posted
                            and k.get("score", 0) >= c["post_min_score"] - 15 and not is_duplicate(job, k, aid)):
                        if not pick or k.get("score", 0) > pick[1].get("score", 0):
                            pick = (job, k)
            if pick:
                made = posting.enqueue(pick[0], pick[1], [aid], at=nxt)
                why = "a clip that hadn't gone to this page yet"
            else:
                made, why = [], ""
                for p in sorted(growth._posted([aid], 365), key=lambda x: -(x["views"] or 0))[:10]:
                    if now - p["posted_at"] < 14 * 86400 or p.get("recycle_of"):
                        continue
                    job, k = _clip_of(p)
                    if k:
                        made = posting.enqueue(job, k, [aid], at=nxt, repeat_of=p["id"])
                        why = "an old hit again"
                        break
            if made:
                filled += 1
                creators.log(c["id"], f"Empty slot at {time.strftime('%H:%M', time.localtime(nxt))} filled with {why}.")
    return filled


# ------------------------------------------------------------------ 11. streamer finder, 16. competitor tracker
def find_streamers(game: str, search=None) -> list:
    """Channels posting the game that are getting views, that aren't your creators yet, with a ready message."""
    from . import permission, trends
    vids = (search or trends.trending)(game)
    have = {u.rstrip("/").lower() for c in creators.all_creators() for u in c.get("channels", {}).values()}
    names = {c["name"].lower() for c in creators.all_creators()}
    by = {}
    for v in vids:
        ch = v.get("channel") or ""
        url = v.get("channel_url") or ""
        if not ch or ch.lower() in names or url.rstrip("/").lower() in have:
            continue
        r = by.setdefault(ch, {"name": ch, "url": url, "views": 0, "videos": 0, "top": v["title"]})
        r["views"] += v.get("views", 0)
        r["videos"] += 1
    out = sorted(by.values(), key=lambda r: -r["views"])[:15]
    for r in out:
        r["message"] = permission.message({"name": r["name"], "audience": "india"})
    return out


def competitors(list_feed=None) -> list:
    """The most-viewed recent Shorts of the clip pages you follow (Settings: competitor pages)."""
    from . import autofetch
    urls = [u for u in (accounts.settings().get("competitors") or [])][:8]
    mine = [c["name"].lower() for c in creators.all_creators()]
    out = []
    for u in urls:
        try:
            vids = (list_feed or autofetch.list_feed)(u.rstrip("/") + "/shorts", 30)
        except Exception as e:  # noqa: BLE001
            out.append({"page": u, "error": str(e)[:120], "videos": []})
            continue
        from . import ytstrategy
        allv = [dict(v, channel=u) for v in vids]
        med = statistics.median([v.get("views") or 0 for v in allv]) if len(allv) >= 4 else 0
        for v in allv:
            v["about_yours"] = [n for n in mine if n and n in (v.get("title") or "").lower()]
            v["multiple"] = round((v.get("views") or 0) / med, 1) if med else None     # yt-viral: vs the page's own median
            v["formula"] = ytstrategy.classify(v.get("title") or "")
        top = sorted(allv, key=lambda v: -(v["multiple"] or 0) if med else -(v.get("views") or 0))[:6]
        out.append({"page": u, "videos": top, "all": allv, "median": int(med)})
    return out


# ------------------------------------------------------------------ 12. English-subtitle version
def english_words(words: list, ask=None) -> list:
    """The caption lines translated to English, each spread over the time the original line took."""
    from . import brain, render
    groups = render._groups(words, 4)
    if not groups:
        return []
    lines = [" ".join(w["w"] for w in g) for g in groups]
    if ask is None:
        def ask():
            out, _, _ = brain.ask_ai(
                "Translate each caption line of a Hinglish gaming clip into short, natural English (same number of "
                "lines, same order, keep slang energy, no extra words):\n" + "\n".join(f"{i + 1}. {brain._safe(t, 120)}" for i, t in enumerate(lines)),
                schema={"type": "OBJECT", "properties": {"lines": {"type": "ARRAY", "items": {"type": "STRING"}}},
                        "required": ["lines"]}, purpose="English subtitles")
            return out["lines"]
    tr = [brain._text(x, 120) for x in ask()]
    if len(tr) != len(lines):
        raise ValueError("translation lost lines")
    out = []
    for g, t in zip(groups, tr):
        ws = t.split() or ["…"]
        s, e = g[0]["s"], g[-1]["e"]
        step = (e - s) / len(ws)
        out += [{"w": w, "s": round(s + i * step, 3), "e": round(s + (i + 1) * step, 3)} for i, w in enumerate(ws)]
    return out


def wants_english_version(c) -> bool:
    if not c or not c.get("en_subs") or c.get("audience", "india") != "india":
        return False
    return any(a["lang"] == "english" for a in accounts.list_accounts() if a["id"] in c["accounts"])


# ------------------------------------------------------------------ 13. best cover frame
def best_cover_ms(path: Path) -> int:
    """The loudest moment of the clip (its biggest reaction), a little after it starts."""
    from . import fx
    try:
        with tempfile.TemporaryDirectory() as d:
            p, _ = fx.peak(path, 0.0, 600.0, Path(d))
        return int(max(0.3, (p or 1.2) + 0.25) * 1000)
    except Exception:  # noqa: BLE001
        return 1200


# ------------------------------------------------------------------ 14. hook formats (used by brain)
def format_rule(c) -> str:
    if not c or not c.get("formats"):
        return ""
    picks = random.sample(FORMATS, 3)
    return ("\nHook format: write this clip's hook in one of these proven formats (pick the one that fits the moment, "
            "fill the <...>): " + " | ".join(picks) + "\n")


# ------------------------------------------------------------------ status for the Setup card
def summary(cid) -> dict:
    d = _state()
    return {"notes": style_notes(cid), "learned_at": (d.get("style", {}).get(cid) or {}).get("at"),
            "hook_wins": d.get("hook_wins", {}).get(cid, [])[-5:],
            "slowed": [a["name"] for a in accounts.list_accounts() if slowed(a["id"])]}


# ------------------------------------------------------------------ the loop
_last = {}


def round_for_user():
    for name, every, fn in (("order", 0, smart_order), ("viral", 0, _viral), ("fill", 3600, _fill_slots),
                            ("copyright", 2 * 3600, _copyright), ("hooks", 6 * 3600, _hook_results),
                            ("reach", 12 * 3600, _reach), ("learn", 6 * 3600, _weekly_learning)):
        key = (ctx.uid(), name)
        if time.time() - _last.get(key, 0) < every:
            continue
        _last[key] = time.time()
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


def _loop():
    time.sleep(120)
    while True:
        for uid in auth.user_ids():
            try:
                with ctx.as_user(uid):
                    round_for_user()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(EVERY)


def start():
    threading.Thread(target=_loop, daemon=True).start()
